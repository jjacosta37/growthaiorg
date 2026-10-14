"""Keyword search data interface. Pipelines depend on this, not on Apify, so another source of
search volume and difficulty can be swapped in without touching pipeline logic."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

# The markets the lookup supports, as ISO country codes, with each one's main language.
# The keyword actor accepts exactly these countries (checked against a live run, 2026-10-13).
MARKETS: dict[str, tuple[str, str]] = {
    "US": ("United States", "en"), "GB": ("United Kingdom", "en"), "CA": ("Canada", "en"),
    "AU": ("Australia", "en"), "NZ": ("New Zealand", "en"), "IE": ("Ireland", "en"), "IN": ("India", "en"),
    "SG": ("Singapore", "en"), "ZA": ("South Africa", "en"), "DE": ("Germany", "de"), "AT": ("Austria", "de"),
    "CH": ("Switzerland", "de"), "FR": ("France", "fr"), "BE": ("Belgium", "nl"), "NL": ("Netherlands", "nl"),
    "ES": ("Spain", "es"), "MX": ("Mexico", "es"), "IT": ("Italy", "it"), "PT": ("Portugal", "pt"),
    "BR": ("Brazil", "pt"), "PL": ("Poland", "pl"), "SE": ("Sweden", "sv"), "DK": ("Denmark", "da"),
    "FI": ("Finland", "fi"), "CZ": ("Czechia", "cs"), "UA": ("Ukraine", "uk"), "TR": ("Turkey", "tr"),
    "JP": ("Japan", "ja"),
}
LANGUAGES = {"en", "de", "fr", "nl", "es", "it", "pt", "pl", "sv", "da", "fi", "cs", "uk", "tr", "ja"}
MAX_KEYWORD_CHARS = 80
MAX_KEYWORD_WORDS = 10


def normalize_keyword(keyword: str) -> str:
    """The form a keyword is looked up and matched under: lowercase, single-spaced."""
    return " ".join(keyword.lower().split())


def is_lookup_keyword(keyword: str) -> bool:
    """True if the keyword is within the provider's length and word limits."""
    k = normalize_keyword(keyword)
    return bool(k) and len(k) <= MAX_KEYWORD_CHARS and len(k.split()) <= MAX_KEYWORD_WORDS


@dataclass
class KeywordMetrics:
    """One keyword's search data in one market."""

    volume: int  # average monthly searches
    difficulty: int | None  # 0-100 on the provider's scale; None when it has none


@dataclass
class KeywordQuery:
    """Keywords to look up, in one market (an ISO country code and a language code)."""

    keywords: list[str]
    country: str = "US"
    language: str = "en"


@dataclass
class KeywordLookupResult:
    """Metrics per normalised keyword. A keyword the provider has no data for is reported in
    `without_data` and counts as zero volume; one missing from both was not looked up."""

    metrics: dict[str, KeywordMetrics] = field(default_factory=dict)
    without_data: list[str] = field(default_factory=list)
    provider: str = ""
    resource_id: str = ""
    external_run_id: str = ""
    cost_usd: Decimal = Decimal(0)
    error: str = ""
    status: str = ""
    duration_ms: int = 0
    items_raw: int = 0

    @property
    def ok(self) -> bool:
        """True unless the lookup failed."""
        return not self.error


class KeywordSource(Protocol):
    """Where keyword search data comes from."""

    name: str

    def lookup(self, query: KeywordQuery) -> KeywordLookupResult:
        """Monthly search volume and difficulty for each keyword in one market."""
        ...
