"""Run lifecycle helpers shared by every pipeline."""

import logging
from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from .models import AgentRun, RunEvent

log = logging.getLogger(__name__)


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

    def event(self, message: str, level: str = RunEvent.Level.INFO, **data) -> None:
        RunEvent.objects.create(run=self.run, level=level, message=message[:500], data=data)
        log.info("run %s [%s] %s", self.run.pk, level, message)

    def step(self, message: str, **data) -> None:
        self.run.current_step = message[:255]
        self.run.save(update_fields=["current_step"])
        self.event(message, **data)

    def success(self, message: str, **data) -> None:
        self.event(message, RunEvent.Level.SUCCESS, **data)

    def warning(self, message: str, **data) -> None:
        self.run.stats.setdefault("warnings", []).append(message)
        self.run.save(update_fields=["stats"])
        self.event(message, RunEvent.Level.WARNING, **data)

    def error(self, message: str, **data) -> None:
        self.run.stats.setdefault("errors", []).append(message)
        self.run.save(update_fields=["stats"])
        self.event(message, RunEvent.Level.ERROR, **data)


@contextmanager
def running(run: AgentRun):
    """Mark a run running; on exit mark it succeeded / partial (errors logged) / failed (exception)."""
    run.status = AgentRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    reporter = RunReporter(run)
    try:
        yield reporter
    except Exception as exc:
        log.exception("run %s failed", run.pk)
        run.refresh_from_db(fields=["stats"])
        run.status = AgentRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:5000]
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
