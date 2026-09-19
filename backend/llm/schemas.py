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


# --- Content Agent ----------------------------------------------------------------------


class TopicProposal(BaseModel):
    title: str = Field(description="Working title of the article.")
    angle: str = Field(description="One or two sentences: the specific take and what the reader will learn.")
    target_keywords: list[str] = Field(description="2-5 search keywords (hypotheses; no volumes).")
    pillar: str = Field(description="Which Content Strategy pillar this belongs to.")
    why: str = Field(description="One line: why this topic, now, for this audience.")


@register
class TopicProposals(BaseModel):
    topics: list[TopicProposal]


@register
class BlogPostDraft(BaseModel):
    title: str = Field(description="SEO title, ideally under 60 characters.")
    meta_description: str = Field(description="Under 155 characters; a clear promise of what the reader learns.")
    slug: str = Field(description="URL slug: lowercase words separated by hyphens.")
    target_keywords: list[str] = Field(description="Primary keyword first, then 2-4 secondary keywords.")
    body_md: str = Field(description="The full article in Markdown, starting at the first H2 (no H1).")


@register
class ProjectIdentity(BaseModel):
    product_name: str = Field(description="The product or company name as the website presents it.")
    industry_pack: str = Field(description="The id of the best-matching policy pack from the list given.")
    reason: str = Field(description="One line: why that pack fits.")


# --- X Agent ----------------------------------------------------------------------------


@register
class XPostItem(BaseModel):
    format: str = Field(description="The format id this item follows.")
    angle: str = Field(description="One line: the specific idea or topic of this item.")
    posts: list[str] = Field(description="One entry for a single post; several for a thread, in order.")


@register
class XPostBatch(BaseModel):
    items: list[XPostItem]
