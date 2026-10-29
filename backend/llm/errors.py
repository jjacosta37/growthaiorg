class LLMConfigError(Exception):
    """Credentials missing or rejected. Deliberately NOT an LLMError: pipelines catch LLMError
    per step and carry on, but a config problem should fail the whole run immediately."""


class LLMError(Exception):
    """Base error. `call` is the LLMCall row recorded for the failed attempt, when there is one.

    Deliberately no `public` text: the UI shows the generic failure (apps.core.errors), and the
    detail is in the log, Sentry and the LLMCall row.
    """

    def __init__(self, message, *, call=None):
        super().__init__(message)
        self.call = call


class LLMRefused(LLMError):
    """stop_reason == "refusal"."""


class LLMTruncated(LLMError):
    """stop_reason == "max_tokens": the output was cut off, so it can't be trusted or parsed."""


class LLMOutputInvalid(LLMError):
    """Structured output failed schema validation (after the one retry)."""


def error_for_status(status: str) -> type[LLMError]:
    """The LLMError subclass that matches a failed LLMCall's status (sync and batch share it)."""
    from .models import LLMCall

    return {
        LLMCall.Status.REFUSED: LLMRefused,
        LLMCall.Status.TRUNCATED: LLMTruncated,
        LLMCall.Status.INVALID_OUTPUT: LLMOutputInvalid,
    }.get(status, LLMError)
