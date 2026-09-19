"""Pydantic models for structured outputs, registered by name so prompt files can reference them.

Keep these flat and simple: they're converted with `anthropic.transform_schema`, and structured
outputs only support a subset of JSON Schema (constraints like min/max are moved into descriptions).
"""

from pydantic import BaseModel, Field

_registry: dict[str, type[BaseModel]] = {}


def register(cls: type[BaseModel]) -> type[BaseModel]:
    _registry[cls.__name__] = cls
    return cls


def get_schema(name: str) -> type[BaseModel]:
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(f"Unknown output schema {name!r}; register it in llm/schemas.py") from None


@register
class SmokeResult(BaseModel):
    ok: bool
    echo: str = Field(description="The word you were asked to echo back.")
