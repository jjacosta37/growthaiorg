"""Production error visibility: durable tracebacks, the DRF handler, and the Sentry guard."""

import logging

import pytest

from apps.agents.models import AgentRun, RunEvent
from apps.agents.runs import RunReporter, create_run, running
from config.exceptions import exception_handler
from config.observability import API_LOGGER, RUN_EVENTS_LOGGER, init_sentry

# --- Run failures ------------------------------------------------------------------------


def _failing_run(project):
    run = create_run(project, AgentRun.Kind.REDDIT)
    with running(run):
        raise ValueError("the pipeline broke")
    return run


@pytest.mark.django_db
def test_failed_run_stores_summary_and_traceback(project):
    """`running()` swallows the exception, so the DB row is the only lasting record of it."""
    run = _failing_run(project)
    run.refresh_from_db()

    assert run.status == AgentRun.Status.FAILED
    assert run.finished_at is not None
    assert run.current_step == ""
    # Summary first (the UI shows one line), full traceback after it.
    assert run.error.startswith("ValueError: the pipeline broke")
    assert "Traceback (most recent call last)" in run.error
    assert "test_observability.py" in run.error


@pytest.mark.django_db
def test_failed_run_still_reports_an_error_event(project):
    run = _failing_run(project)
    event = RunEvent.objects.filter(run=run, level=RunEvent.Level.ERROR).last()
    assert event is not None
    assert "the pipeline broke" in event.message


@pytest.mark.django_db
def test_run_failure_does_not_propagate(project):
    """Beat calls the agent task synchronously; a raise here would fail the whole tick."""
    run = create_run(project, AgentRun.Kind.REDDIT)
    with running(run):  # must not raise out of the context manager
        raise RuntimeError("boom")


# --- Handled failures --------------------------------------------------------------------
# A pipeline that catches an error and carries on is the common case (the run ends PARTIAL).
# These must still be reported, or a run where every draft failed looks quiet.


@pytest.fixture
def captured(monkeypatch):
    """Records what RunReporter sends to Sentry, without initialising the SDK."""
    calls = []
    monkeypatch.setattr("apps.agents.runs.sentry_sdk.capture_exception", calls.append)
    return calls


@pytest.mark.django_db
def test_reporter_error_reports_the_exception(project, captured, caplog):
    run = create_run(project, AgentRun.Kind.REDDIT)
    exc = ValueError("the model is overloaded")

    with caplog.at_level(logging.ERROR, logger=RUN_EVENTS_LOGGER):
        RunReporter(run).error("Couldn't draft a reply", exc=exc)

    assert captured == [exc]  # grouped by exception type and stack, not by message text
    assert "Couldn't draft a reply" in caplog.text
    assert caplog.records[-1].levelno == logging.ERROR  # not INFO, as it used to be
    assert run.stats["errors"] == ["Couldn't draft a reply"]


@pytest.mark.django_db
def test_reporter_error_without_an_exception_is_not_reported(project, captured):
    """A count like "3 posts couldn't be scored" has no stack; the RunEvent carries it."""
    run = create_run(project, AgentRun.Kind.REDDIT)
    RunReporter(run).error("3 post(s) couldn't be scored")

    assert captured == []
    assert RunEvent.objects.filter(run=run, level=RunEvent.Level.ERROR).exists()


@pytest.mark.django_db
def test_reporter_warning_is_never_reported(project, captured, caplog):
    """Tolerated degradation belongs in the log and the run, not in the error tracker."""
    run = create_run(project, AgentRun.Kind.REDDIT)

    with caplog.at_level(logging.WARNING, logger=RUN_EVENTS_LOGGER):
        RunReporter(run).warning("Browser rendering had a problem", exc=ValueError("apify down"))

    assert captured == []
    assert caplog.records[-1].levelno == logging.WARNING


@pytest.mark.django_db
def test_run_events_mirror_their_level_to_the_log(project, caplog):
    run = create_run(project, AgentRun.Kind.REDDIT)
    reporter = RunReporter(run)

    with caplog.at_level(logging.INFO, logger=RUN_EVENTS_LOGGER):
        reporter.step("Fetching posts")
        reporter.success("Drafted 2 replies")

    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.INFO, logging.INFO]


def test_noisy_loggers_are_ignored_by_sentry():
    """Both mirror the same message many ways; as events they would group into one issue."""
    from sentry_sdk.integrations.logging import _IGNORED_LOGGERS

    try:
        init_sentry(dsn="https://k@o0.ingest.sentry.io/0", environment="test",
                    release=None, local_variables=False)
        assert RUN_EVENTS_LOGGER in _IGNORED_LOGGERS
        assert API_LOGGER in _IGNORED_LOGGERS
    finally:
        import sentry_sdk

        sentry_sdk.init(dsn="")  # leave the SDK inactive for every other test


# --- DRF exception handler ---------------------------------------------------------------


class _View:
    pass


def _context():
    return {"view": _View(), "request": None}


def test_handler_logs_unhandled_exceptions(caplog):
    with caplog.at_level(logging.ERROR, logger="apps.api"):
        response = exception_handler(ValueError("nope"), _context())

    assert response is None  # DRF re-raises it; Django's middleware (and Sentry) take over
    assert "unhandled exception in _View" in caplog.text
    assert "ValueError: nope" in caplog.text  # exc_info attached


def test_handler_stays_quiet_for_client_errors(caplog):
    from rest_framework.exceptions import NotFound

    with caplog.at_level(logging.ERROR, logger="apps.api"):
        response = exception_handler(NotFound(), _context())

    assert response.status_code == 404
    assert caplog.text == ""


# --- Sentry guard ------------------------------------------------------------------------


def test_sentry_is_off_without_a_dsn():
    """Tests raise constantly; none of it may reach a real project."""
    assert init_sentry(dsn="", environment="test", release=None, local_variables=False) is False


def test_settings_do_not_enable_sentry_under_test(settings):
    assert settings.SENTRY_ENABLED is False


# --- External calls ----------------------------------------------------------------------
# An Apify call is the slowest, priciest part of a run and used to be the least visible: the
# usage row was written and nothing reported it. `record_external` does both at once.


def _reporter(project):
    run = create_run(project, AgentRun.Kind.REDDIT)
    return run, RunReporter(run)


@pytest.mark.django_db
def test_external_call_is_both_costed_and_reported(project):
    from decimal import Decimal

    from apps.agents.external import record_external
    from apps.agents.models import ExternalUsage

    run, reporter = _reporter(project)
    record_external(run, reporter, provider="apify", purpose="reddit_search", resource_id="acme/scraper",
                    external_run_id="apify_1", status="SUCCEEDED", items=12, cost_usd=Decimal("0.031"),
                    duration_ms=4200, message="Searched 3 queries", queries=3)

    usage = ExternalUsage.objects.get()
    assert (usage.status, usage.duration_ms, usage.items) == ("SUCCEEDED", 4200, 12)

    event = RunEvent.objects.filter(run=run).last()
    assert event.level == RunEvent.Level.INFO
    assert event.data["external_run_id"] == "apify_1"
    assert event.data["duration_ms"] == 4200 and event.data["queries"] == 3
    # Decimal is not JSON-serialisable; the helper is what keeps it out of `data`.
    assert event.data["cost_usd"] == pytest.approx(0.031)


@pytest.mark.django_db
def test_a_degraded_external_call_warns_rather_than_failing_the_run(project):
    from apps.agents.external import record_external

    run, reporter = _reporter(project)
    record_external(run, reporter, provider="apify", purpose="reddit_search",
                    status="TIMED-OUT", error="Apify run did not finish in time",
                    message="Searched 3 queries")

    event = RunEvent.objects.filter(run=run).last()
    assert event.level == RunEvent.Level.WARNING
    assert event.data["status"] == "TIMED-OUT"
    run.refresh_from_db()
    assert run.stats["warnings"] and not run.stats.get("errors")  # degraded, not abandoned


# --- Tool spans --------------------------------------------------------------------------


def test_trace_tool_is_a_usable_no_op_when_tracing_is_off(settings):
    """Tracing is off under test, and a span must still hand back somewhere to write."""
    from llm.tracing import trace_tool

    assert settings.LANGSMITH_TRACING is False
    with trace_tool("apify.reddit_search", inputs={"q": "x"}) as outputs:
        outputs.update(items=3)
    assert outputs == {"items": 3}


def test_trace_tool_lets_the_bodys_exception_through():
    """Observability never swallows the caller's failure."""
    from llm.tracing import trace_tool

    with pytest.raises(ValueError, match="boom"), trace_tool("apify.reddit_search"):
        raise ValueError("boom")


# --- Conventions new agents inherit ------------------------------------------------------
# `running()` gives every pipeline its span, status lifecycle and Sentry tags for free, but
# an external call is invisible unless its author opts in. These guard the two chokepoints
# so a new agent can't quietly reintroduce the gap.


def _source_files():
    from pathlib import Path

    from django.conf import settings

    root = Path(settings.BASE_DIR)
    return [p for p in root.rglob("*.py")
            if not {"tests", "migrations"} & set(p.parts)]


def test_external_usage_rows_are_only_written_by_record_external():
    """Writing the row and reporting the call are one action, so the row has one writer.

    A new provider that creates its own ExternalUsage would be costed but invisible — the
    exact gap the Apify Reddit search had.
    """
    offenders = [str(p) for p in _source_files()
                 if "ExternalUsage.objects.create" in p.read_text() and p.name != "external.py"]
    assert offenders == [], "write the row via apps.agents.external.record_external instead"


def test_langsmith_is_only_imported_by_the_tracing_module():
    """The same containment as the Anthropic SDK, for the same reason.

    `llm/tracing.py` is where tracing is made unable to break a run: span creation is
    guarded, `LANGSMITH_TRACING` is honoured, and a wrap failure degrades to an untraced
    client. Reach for langsmith anywhere else and a pipeline inherits none of that — a
    version mismatch or an unserialisable payload takes down the run it was watching.
    """
    import re

    imports_langsmith = re.compile(r"^\s*(?:from|import)\s+langsmith", re.MULTILINE)
    offenders = [str(p) for p in _source_files()
                 if imports_langsmith.search(p.read_text()) and p.name != "tracing.py"]
    assert offenders == [], "import from llm.tracing instead; it is what fails safe"
