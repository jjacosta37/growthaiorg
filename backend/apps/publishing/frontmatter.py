"""The file a blog post becomes in the connected repository, and the settings that shape it.

A post is one Markdown file named from its slug, with a YAML frontmatter header. Sites name
their fields differently, so each standard field can be renamed and constant fields can be
added. Nothing here is a template language: values are written with `yaml.safe_dump`, so a
title containing quotes, `---` or newlines can't break out of the header.
"""

import re
from datetime import date

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from apps.policy.service import with_blog_disclaimer

STANDARD_FIELDS = ("title", "description", "slug", "keywords", "date")
KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,39}$")
SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
MAX_CONSTANTS = 10
MAX_CONSTANT_CHARS = 200
MAX_FOLDER_CHARS = 200

Scalar = str | bool | int | float


def _check_key(key: str) -> str:
    key = key.strip()
    if not KEY_PATTERN.match(key):
        raise ValueError(f"“{key[:40]}” isn't a valid field name: start with a letter, then letters, "
                         "digits, - or _ (40 characters at most)")
    return key


class ConstantField(BaseModel):
    """A field written into every post's frontmatter with the same value, e.g. an author."""

    key: str
    value: Scalar

    @field_validator("key")
    @classmethod
    def valid_key(cls, v: str) -> str:
        """A plain YAML key."""
        return _check_key(v)

    @field_validator("value")
    @classmethod
    def short_value(cls, v: Scalar) -> Scalar:
        """Text values are one line and short."""
        if isinstance(v, str):
            v = v.strip()
            if len(v) > MAX_CONSTANT_CHARS or "\n" in v:
                raise ValueError(f"Values are one line of at most {MAX_CONSTANT_CHARS} characters")
        return v


class FrontmatterSettings(BaseModel):
    """How a project's posts name their frontmatter fields."""

    field_names: dict[str, str] = Field(default_factory=dict)
    constant_fields: list[ConstantField] = Field(default_factory=list, max_length=MAX_CONSTANTS)

    @field_validator("field_names")
    @classmethod
    def known_fields(cls, v: dict[str, str]) -> dict[str, str]:
        """Only standard fields can be renamed; a blank name means the standard one."""
        unknown = set(v) - set(STANDARD_FIELDS)
        if unknown:
            raise ValueError(f"Unknown field: {sorted(unknown)[0]}")
        return {k: _check_key(name) for k, name in v.items() if name and name.strip() and name.strip() != k}

    @model_validator(mode="after")
    def unique_keys(self) -> "FrontmatterSettings":
        """Every field in the file has a different name."""
        keys = [self.name_of(f) for f in STANDARD_FIELDS] + [c.key for c in self.constant_fields]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"Two fields are both named “{dupes[0]}”")
        return self

    def name_of(self, field: str) -> str:
        return self.field_names.get(field, field)


def clean_folder(folder: str) -> str:
    """A repository folder as a relative path without leading or trailing slashes ("" = root).

    Raises:
        ValueError: The folder climbs out of the repository, is hidden (".github"), or has
            characters outside letters, digits, ".", "-" and "_".
    """
    folder = folder.strip().strip("/")
    if not folder:
        return ""
    if len(folder) > MAX_FOLDER_CHARS:
        raise ValueError(f"Folder paths are at most {MAX_FOLDER_CHARS} characters")
    for segment in folder.split("/"):
        if not SEGMENT_PATTERN.match(segment) or segment in (".", ".."):
            raise ValueError("Use a folder path like content/blog: letters, digits, '.', '-' and '_', "
                             "with no hidden folders")
    return folder


def post_path(folder: str, slug: str) -> str:
    """Where a post lives in the repository."""
    return f"{folder}/{slug}.md" if folder else f"{slug}.md"


def frontmatter(content: dict, fm: FrontmatterSettings, post_date: date) -> str:
    """The YAML header block (without the `---` fences) for a post."""
    values = {
        "title": content["title"],
        "description": content["meta_description"],
        "slug": content["slug"],
        "keywords": list(content["keywords"]),
        "date": post_date,
    }
    data = {fm.name_of(k): values[k] for k in STANDARD_FIELDS}
    data.update({c.key: c.value for c in fm.constant_fields})
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=10_000)


def render_post(content: dict, fm: FrontmatterSettings, post_date: date, disclaimer: str = "") -> str:
    """The whole file: frontmatter, then the body, then the blog disclaimer if it isn't there."""
    body = with_blog_disclaimer(content["body_md"].strip(), disclaimer)
    return f"---\n{frontmatter(content, fm, post_date)}---\n\n{body}\n"


SAMPLE_POST = {
    "title": "A sample post title",
    "meta_description": "One or two sentences that search results show under the title.",
    "slug": "a-sample-post-title",
    "keywords": ["primary keyword", "secondary keyword"],
    "body_md": "## First section\n\n…",
}
