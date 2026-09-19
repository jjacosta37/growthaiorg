class LLMError(Exception):
    """Base error. `call` is the LLMCall row recorded for the failed attempt, when there is one."""

    def __init__(self, message, *, call=None):
        super().__init__(message)
        self.call = call


class LLMRefused(LLMError):
    """stop_reason == "refusal"."""


class LLMTruncated(LLMError):
    """stop_reason == "max_tokens": the output was cut off, so it can't be trusted or parsed."""


class LLMOutputInvalid(LLMError):
    """Structured output failed schema validation (after the one retry)."""
