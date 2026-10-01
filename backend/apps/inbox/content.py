"""Content shape per draft kind. Every DraftVersion.content is validated against one of these."""

from pydantic import BaseModel, Field, field_validator


class RedditCommentContent(BaseModel):
    """A Reddit comment draft: the body, plus who the model thought it was writing for."""

    body: str = Field(min_length=1)
    poster_read: str = ""  # who the model thought it was writing for; shown next to the draft


class XContent(BaseModel):
    """A single post is a one-item list; a thread is several. format/angle record how it was planned
    (used to vary formats and avoid repeats)."""

    posts: list[str] = Field(min_length=1)
    format: str = ""
    angle: str = ""

    @field_validator("posts")
    @classmethod
    def non_empty(cls, posts):
        if any(not p.strip() for p in posts):
            raise ValueError("posts can't be empty")
        return posts


class BlogContent(BaseModel):
    title: str = Field(min_length=1)
    meta_description: str
    slug: str
    keywords: list[str]
    body_md: str = Field(min_length=1)


CONTENT_MODELS: dict[str, type[BaseModel]] = {
    "reddit_comment": RedditCommentContent,
    "x_post": XContent,
    "x_thread": XContent,
    "blog_post": BlogContent,
}


def validate_content(kind: str, content: dict) -> dict:
    return CONTENT_MODELS[kind].model_validate(content).model_dump()


def as_text(kind: str, content: dict) -> str:
    """What "Copy" puts on the clipboard."""
    if kind == "reddit_comment":
        return content["body"]
    if kind in ("x_post", "x_thread"):
        return "\n\n".join(content["posts"])
    return f"# {content['title']}\n\n{content['body_md']}"
