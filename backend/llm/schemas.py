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


# --- Onboarding / context -------------------------------------------------------------


class Competitor(BaseModel):
    name: str
    url: str = Field(description="Homepage URL, or an empty string if unknown.")


@register
class ProjectFacts(BaseModel):
    product_summary: str = Field(description="Two sentences: what the product is and who it's for.")
    competitors: list[Competitor]


class SubredditSuggestion(BaseModel):
    name: str = Field(description="Subreddit name without the r/ prefix.")
    reason: str = Field(description="One line: why the target audience asks relevant questions there.")


@register
class RedditSuggestions(BaseModel):
    subreddits: list[SubredditSuggestion]
    keywords: list[str] = Field(description="Search phrases people use when asking about problems the product solves.")
