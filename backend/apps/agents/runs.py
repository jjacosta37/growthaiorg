"""Run lifecycle helpers shared by every pipeline."""

import logging
import traceback
from contextlib import contextmanager

import sentry_sdk
from django.db import transaction
from django.utils import timezone

from llm.tracing import trace_group

from .models import AgentRun, RunEvent

log = logging.getLogger(__name__)

# The mirror of every RunEvent to the log stream. It is a separate logger because Sentry
# ignores it (config/observability.py): these messages are interpolated one-offs, so letting
# them file issues would group every pipeline failure under one useless "run %s [%s] %s".
# The trail is kept as breadcrumbs instead, and real exceptions are captured explicitly.
events_log = logging.getLogger(f"{__name__}.events")

_LOG_LEVEL = {
    RunEvent.Level.INFO: logging.INFO,
    RunEvent.Level.SUCCESS: logging.INFO,
    RunEvent.Level.WARNING: logging.WARNING,
    RunEvent.Level.ERROR: logging.ERROR,
}
_BREADCRUMB_LEVEL = {
    RunEvent.Level.INFO: "info",
    RunEvent.Level.SUCCESS: "info",
    RunEvent.Level.WARNING: "warning",
    RunEvent.Level.ERROR: "error",
}


class RunConflict(Exception):
    """A run of this kind is already active."""


def create_run(project, kind: str, *, trigger=AgentRun.Trigger.MANUAL, params=None,
               exclusive_kinds: tuple[str, ...] | None = None) -> AgentRun:
    """Create a queued run. Refuses if an active run of `exclusive_kinds` (default: same kind) exists."""
    kinds = exclusive_kinds or (kind,)
    with transaction.atomic():
        busy = AgentRun.objects.select_for_update().filter(
            project=project, kind__in=kinds, status__in=AgentRun.ACTIVE
        )
        if busy.exists():
            raise RunConflict(f"A {kind} run is already in progress")
        return AgentRun.objects.create(project=project, kind=kind, trigger=trigger, params=params or {})


class RunReporter:
    """Writes progress for a run: `step()` updates the status line, `event()` appends to the log."""

    def __init__(self, run: AgentRun):
        self.run = run

    def event(self, message: str, level: str = RunEvent.Level.INFO, *, exc: BaseException | None = None,
              **data) -> None:
        RunEvent.objects.create(run=self.run, level=level, message=message[:500], data=data)
        events_log.log(_LOG_LEVEL[level], "run %s [%s] %s", self.run.pk, level, message, exc_info=exc)
        # Explicit, because the logger above is ignored by Sentry. This is the trail that
        # makes a captured failure readable: what the run had done by the time it broke.
        sentry_sdk.add_breadcrumb(category="run", level=_BREADCRUMB_LEVEL[level], message=message)

    def step(self, message: str, **data) -> None:
        self.run.current_step = message[:255]
        self.run.save(update_fields=["current_step"])
        self.event(message, **data)

    def success(self, message: str, **data) -> None:
        self.event(message, RunEvent.Level.SUCCESS, **data)

    def warning(self, message: str, *, exc: BaseException | None = None, **data) -> None:
        """Degradation the run tolerated. Logged and left as a breadcrumb, never an issue."""
        self.run.stats.setdefault("warnings", []).append(message)
        self.run.save(update_fields=["stats"])
        self.event(message, RunEvent.Level.WARNING, exc=exc, **data)

    def error(self, message: str, *, exc: BaseException | None = None, **data) -> None:
        """A step of the run failed. Pass `exc` whenever one is in hand: it is what gets
        reported, and it groups by exception type and stack rather than by message text."""
        self.run.stats.setdefault("errors", []).append(message)
        self.run.save(update_fields=["stats"])
        self.event(message, RunEvent.Level.ERROR, exc=exc, **data)
        if exc is not None:
            sentry_sdk.capture_exception(exc)


@contextmanager
def running(run: AgentRun):
    """Mark a run running; on exit mark it succeeded / partial (errors logged) / failed (exception).

    A pipeline can set run.status = WAITING_BATCH and return; a follow-up task later re-enters
    `running(run)` to finish it (started_at is kept).

    Everything inside is one LangSmith span, so a run's LLM calls appear as children of it
    rather than as scattered root traces.

    The exception is swallowed on purpose: the run's status is the contract the API and UI
    read, and re-raising would fail the whole beat tick (apps/agents/tasks.py calls this
    synchronously). It is still reported — `log.exception` becomes a Sentry issue, tagged
    with the run so a failure can be traced back to a project and pipeline.
    """
    run.status = AgentRun.Status.RUNNING
    run.started_at = run.started_at or timezone.now()
    run.save(update_fields=["status", "started_at"])
    reporter = RunReporter(run)
    tags = {
        "agent_run_id": run.pk,
        "kind": run.kind,
        "trigger": run.trigger,
        "project_id": run.project_id,
    }

    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, str(value))  # str, so enum members don't tag as "Kind.REDDIT"
        with trace_group(f"{run.kind} run #{run.pk}", metadata=tags, inputs={"params": run.params}):
            try:
                yield reporter
            except Exception as exc:
                log.exception("run %s failed", run.pk)
                run.refresh_from_db(fields=["stats"])
                run.status = AgentRun.Status.FAILED
                # Summary first so the UI's one-line view is unchanged, traceback after:
                # truncation then clips the deepest frames, not the useful part.
                run.error = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"[:5000]
                run.current_step = ""
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "error", "current_step", "finished_at"])
                reporter.event(f"Failed: {exc}", RunEvent.Level.ERROR)
                return
            if run.status == AgentRun.Status.WAITING_BATCH:
                return  # a follow-up task will finish it
            run.status = AgentRun.Status.PARTIAL if run.stats.get("errors") else AgentRun.Status.SUCCEEDED
            run.current_step = ""
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "current_step", "finished_at"])
