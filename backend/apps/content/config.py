from typing import Literal

from pydantic import BaseModel, Field, field_validator

from providers.keywords import LANGUAGES, MARKETS

Weight = Literal["off", "low", "medium", "high"]


class OpportunityWeights(BaseModel):
    """How much each signal counts when ranking the topic backlog. "off" leaves a signal out."""

    volume: Weight = "medium"
    ease: Weight = "medium"
    reddit: Weight = "medium"


class ContentAgentConfig(BaseModel):
    """The Content Agent's settings, edited on its agent page."""

    topics_per_run: int = Field(3, ge=1, le=10, description="New topics proposed when the backlog runs low")
    drafts_per_run: int = Field(1, ge=0, le=3, description="Posts drafted per scheduled run")
    min_backlog: int = Field(3, ge=0, le=20, description="Propose new topics when fewer are waiting")
    target_words: int = Field(1500, ge=500, le=3000)
    guidance: str = Field("", max_length=2000, description="Standing instructions for every post")
    search_country: str = Field("US", description="ISO country code of the market keywords are looked up in")
    search_language: str = Field("en", description="Language code keywords are looked up in")
    weights: OpportunityWeights = Field(default_factory=OpportunityWeights)

    @field_validator("search_country")
    @classmethod
    def known_country(cls, v: str) -> str:
        """Only the markets the keyword lookup supports."""
        v = v.strip().upper()
        if v not in MARKETS:
            raise ValueError("Not a supported search market")
        return v

    @field_validator("search_language")
    @classmethod
    def known_language(cls, v: str) -> str:
        """Only the languages the keyword lookup supports."""
        v = v.strip().lower()
        if v not in LANGUAGES:
            raise ValueError("Not a supported search language")
        return v
