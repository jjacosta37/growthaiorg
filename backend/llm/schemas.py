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


# --- Reddit Agent -----------------------------------------------------------------------


@register
class RelevanceScore(BaseModel):
    score: int = Field(description="0-100: how relevant this post is and how well we could help.")
    reason: str = Field(description="One line explaining the score.")
    reply_worthwhile: bool = Field(description="Would a genuinely helpful reply from us add value here?")


@register
class RedditComment(BaseModel):
    body: str = Field(description="The comment, in Reddit markdown.")
    mentions_product: bool = Field(description="True if the comment mentions the product by name.")


# --- Compliance lint (all agents) -------------------------------------------------------


class ComplianceFlag(BaseModel):
    rule: str = Field(description="One of: returns_claim, personalized_advice, disparagement, fabrication, "
                                  "missing_disclosure, promotional, other")
    excerpt: str = Field(description="The exact problematic text from the draft.")
    explanation: str = Field(description="One line: why this breaks the rule.")


@register
class ComplianceLint(BaseModel):
    flags: list[ComplianceFlag]
