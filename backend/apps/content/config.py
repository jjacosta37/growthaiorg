from pydantic import BaseModel, Field


class ContentAgentConfig(BaseModel):
    topics_per_run: int = Field(3, ge=1, le=10, description="New topics proposed when the backlog runs low")
    drafts_per_run: int = Field(1, ge=0, le=3, description="Posts drafted per scheduled run")
    min_backlog: int = Field(3, ge=0, le=20, description="Propose new topics when fewer are waiting")
    target_words: int = Field(1500, ge=500, le=3000)
    guidance: str = Field("", max_length=2000, description="Standing instructions for every post")
