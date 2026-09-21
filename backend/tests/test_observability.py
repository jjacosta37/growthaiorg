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
