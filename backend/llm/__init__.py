"""The single gateway to Claude. Pipelines call `llm.complete(...)`; nothing else imports `anthropic`.

Kept import-light so `import llm` works before Django's app registry is ready.
"""

from .errors import LLMConfigError, LLMError, LLMOutputInvalid, LLMRefused, LLMTruncated


def complete(task, variables=None, **kwargs):
    from .client import complete as _complete

    return _complete(task, variables, **kwargs)


__all__ = ["complete", "LLMConfigError", "LLMError", "LLMOutputInvalid", "LLMRefused", "LLMTruncated"]
