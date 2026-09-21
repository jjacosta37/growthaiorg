"""DRF exception handler.

Sentry already captures exceptions that escape to Django's middleware. This exists so a
server error is *attributable* in the logs — which view, which exception — instead of
appearing as an unlabelled 500. The logger is ignored by Sentry (see observability.py)
to keep one error from being filed twice.
"""

import logging

from rest_framework.views import exception_handler as drf_exception_handler

from .observability import API_LOGGER

log = logging.getLogger(API_LOGGER)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None or response.status_code >= 500:
        view = context.get("view")
        request = context.get("request")
        log.error(
            "unhandled exception in %s (%s %s)",
            type(view).__name__ if view else "?",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
            exc_info=exc,
        )
    return response
