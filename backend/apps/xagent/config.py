from pydantic import BaseModel, Field, field_validator

# Generic post formats. Descriptions go to the model; nothing here is industry-specific.
FORMATS: dict[str, str] = {
    "insight": "One sharp, specific insight or lesson, stated plainly.",
    "how_to": "A compact, concrete tip someone can apply today.",
    "question": "A genuine question to the audience that invites thoughtful replies (not engagement bait).",
    "observation": "A specific, non-obvious observation about the space the product works in.",
    "myth": "A common misconception in this space and what's actually true.",
    "thread": "A short thread that teaches one idea step by step: the first post hooks, the last wraps up.",
    "behind_the_scenes": "A candid note about building the product, using only facts from the context documents.",
}


class XAgentConfig(BaseModel):
    posts_per_run: int = Field(3, ge=1, le=10)
    formats: list[str] = Field(default_factory=lambda: list(FORMATS))
    max_thread_posts: int = Field(5, ge=2, le=10)
    char_limit: int = Field(280, ge=100, le=25000, description="280 for standard accounts; higher for X Premium")
    recent_window: int = Field(30, ge=0, le=200, description="Recent X drafts shown to the model to avoid repeats")
    guidance: str = Field("", max_length=2000)

    @field_validator("formats")
    @classmethod
    def known_formats(cls, v):
        unknown = sorted(set(v) - set(FORMATS))
        if unknown:
            raise ValueError(f"Unknown formats {unknown}; choose from {sorted(FORMATS)}")
        if not v:
            raise ValueError("Enable at least one format")
        return list(dict.fromkeys(v))
