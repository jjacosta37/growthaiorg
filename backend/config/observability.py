"""Error reporting.

Sentry is optional: with no SENTRY_DSN nothing is initialised and nothing leaves the
process, which is how tests and most local runs work. `init_sentry()` is called once
from settings.

Privacy matters more here than in a typical app: every project holds a customer's
crawled website text and unpublished drafts. We send exception types, messages and
stack frames — never request bodies, never local variables (see below).
"""

import logging

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger

# The DRF handler logs 5xx to stdout for attribution; DjangoIntegration already captures
# the same exception, so letting this logger through would file every API 500 twice.
API_LOGGER = "apps.api"

# Mirrors every RunEvent to the log stream. Its messages interpolate titles, counts and
# error text, so as events they would all group under one template. RunReporter adds the
# trail as breadcrumbs and captures the underlying exception itself.
RUN_EVENTS_LOGGER = "apps.agents.runs.events"


def init_sentry(*, dsn: str, environment: str, release: str | None, local_variables: bool) -> bool:
    """Returns True if Sentry was initialised."""
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            # INFO and above become breadcrumbs (so a failed run arrives with its RunEvent
            # trail attached); ERROR and above become issues. This is what turns the
            # existing `log.exception` in apps/agents/runs.py into a reported error.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        # Errors only. Performance units are a separate quota on the free plan and we
        # have LangSmith for the LLM-side timing we actually care about.
        traces_sample_rate=0.0,
        send_default_pii=False,
        max_request_body_size="never",
        # Frame locals are the one place customer content would reliably leak: a crawled
        # page's text sits in a local at the moment a parser raises. Off by default.
        include_local_variables=local_variables,
    )
    ignore_logger(API_LOGGER)
    ignore_logger(RUN_EVENTS_LOGGER)
    return True
