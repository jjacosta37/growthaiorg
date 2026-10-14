"""Search data for topics: monthly volume and difficulty of each topic's candidate keywords.

One provider call per run looks up new proposals and any topics still pending, within a fixed
keyword budget. A topic whose lookup was deferred or failed stays pending and is retried on a
later run; nothing is ever refreshed once it has data.
"""

from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from apps.agents.external import record_external
from apps.agents.models import AgentRun
from apps.agents.runs import RunReporter
from providers.keywords import (
    ApifyKeywordSource,
    FakeKeywordSource,
    KeywordLookupResult,
    KeywordQuery,
    KeywordSource,
    is_lookup_keyword,
    normalize_keyword,
)

from .config import ContentAgentConfig
from .models import BlogTopic

MAX_CANDIDATES = 5


def get_keyword_source() -> KeywordSource:
    """The configured provider: Apify in production, a fake for local dev.

    Raises:
        RuntimeError: Apify is configured but `APIFY_TOKEN` is not set.
    """
    if settings.KEYWORD_SOURCE == "fake":
        return FakeKeywordSource()
    if not settings.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN is not set (or set KEYWORD_SOURCE=fake for local testing)")
    return ApifyKeywordSource(settings.APIFY_TOKEN, settings.APIFY_KEYWORD_ACTOR,
                              max_charge_usd=settings.APIFY_KEYWORD_MAX_CHARGE_USD)


def candidate_keywords(keywords: list[str], title: str) -> list[str]:
    """The keywords to look up for a topic: its valid candidates, most important first.

    A topic without usable keywords (a requested topic with none given) is looked up by its title,
    cut to the provider's limits, so every topic still gets search data.
    """
    candidates = [k for k in dict.fromkeys(normalize_keyword(k) for k in keywords) if is_lookup_keyword(k)]
    if not candidates:
        words = normalize_keyword(title).split()[:10]
        fallback = " ".join(words)[:80].strip()
        candidates = [fallback] if fallback else []
    return candidates[:MAX_CANDIDATES]


@dataclass
class SearchData:
    """A topic's looked-up search data. `metrics` covers every candidate; the primary keyword is
    the one with the highest volume, lower difficulty breaking ties."""

    metrics: list[dict]
    primary_keyword: str
    volume: int
    difficulty: int | None


@dataclass
class LookupOutcome:
    """What one lookup step produced: search data per item (None = still pending), plus counts."""

    data: list[SearchData | None] = field(default_factory=list)
    keywords_looked_up: int = 0
    deferred: int = 0
    failed: int = 0


def choose_primary(metrics: list[dict]) -> dict:
    """Highest volume; at equal volume a known, lower difficulty wins; then the earlier candidate."""
    return max(metrics, key=lambda m: (m["volume"], -(m["difficulty"] if m["difficulty"] is not None
                                                                  else 101)))


def search_data_for(keywords: list[str], result: KeywordLookupResult) -> SearchData | None:
    """A topic's search data from a lookup, or None if any of its keywords got no answer.

    A keyword the provider reports as having no data counts as zero volume.
    """
    without = set(result.without_data)
    metrics = []
    for k in keywords:
        if k in result.metrics:
            m = result.metrics[k]
            metrics.append({"keyword": k, "volume": m.volume, "difficulty": m.difficulty})
        elif k in without:
            metrics.append({"keyword": k, "volume": 0, "difficulty": None})
        else:
            return None
    if not metrics:
        return None
    primary = choose_primary(metrics)
    return SearchData(metrics=metrics, primary_keyword=primary["keyword"], volume=primary["volume"],
                      difficulty=primary["difficulty"])


def look_up(run: AgentRun, reporter: RunReporter, cfg: ContentAgentConfig,
            keyword_lists: list[list[str]]) -> LookupOutcome:
    """Look up search data for several topics in one provider call, within the per-run budget.

    Items are taken in the order given; one whose keywords don't fit the remaining budget is
    deferred, and smaller ones after it may still fit. A failed call leaves every item pending.

    Args:
        keyword_lists: Each topic's candidate keywords (`candidate_keywords`), in priority order.

    Returns:
        One entry per item, in the same order.
    """
    outcome = LookupOutcome(data=[None] * len(keyword_lists))
    budget = settings.KEYWORD_LOOKUPS_PER_RUN
    included: list[int] = []
    keywords: list[str] = []
    for i, kws in enumerate(keyword_lists):
        new = [k for k in kws if k not in keywords]
        if not kws or len(keywords) + len(new) > budget:
            outcome.deferred += 1
            continue
        included.append(i)
        keywords.extend(new)
    if not keywords:
        report_lookup(reporter, run, outcome)
        return outcome

    reporter.step(f"Looking up search data for {len(keywords)} keywords",
                  keywords=len(keywords), topics=len(included), market=f"{cfg.search_country}/{cfg.search_language}")
    try:
        source = get_keyword_source()
    except RuntimeError as exc:
        reporter.warning(f"Keyword lookup unavailable: {exc}", exc=exc)
        outcome.failed = len(included)
        report_lookup(reporter, run, outcome)
        return outcome
    result = source.lookup(KeywordQuery(keywords=keywords, country=cfg.search_country, language=cfg.search_language))
    outcome.keywords_looked_up = len(keywords)
    if result.provider == "apify":
        record_external(
            run, reporter, provider="apify", purpose="keyword_lookup", resource_id=result.resource_id,
            external_run_id=result.external_run_id, status=result.status, items=len(result.metrics),
            cost_usd=result.cost_usd, duration_ms=result.duration_ms, error=result.error,
            message=f"Looked up {len(keywords)} keywords: {len(result.metrics)} with data, "
                    f"{len(result.without_data)} without (${result.cost_usd})",
            keywords=len(keywords), with_data=len(result.metrics), without_data=len(result.without_data),
            items_raw=result.items_raw,
        )
    elif result.error:
        reporter.warning(f"Keyword lookup failed: {result.error}", provider=result.provider)
    for i in included:
        outcome.data[i] = search_data_for(keyword_lists[i], result)
        outcome.failed += outcome.data[i] is None
    report_lookup(reporter, run, outcome)
    return outcome


def report_lookup(reporter: RunReporter, run: AgentRun, outcome: LookupOutcome) -> None:
    """Record the lookup counts on the run, and say what is left pending and why."""
    run.stats.update(keywords_looked_up=outcome.keywords_looked_up, topics_lookup_deferred=outcome.deferred,
                     topics_lookup_failed=outcome.failed)
    run.save(update_fields=["stats"])
    if outcome.deferred or outcome.failed:
        reporter.event(
            f"Search data pending for {outcome.deferred + outcome.failed} topic(s); retried on a later run",
            deferred=outcome.deferred, failed=outcome.failed, budget=settings.KEYWORD_LOOKUPS_PER_RUN,
        )


def apply_search_data(topic: BlogTopic, data: SearchData, cfg: ContentAgentConfig) -> None:
    """Store looked-up search data on a topic and mark it ready (the caller saves)."""
    topic.keyword_metrics = data.metrics
    topic.primary_keyword = data.primary_keyword
    topic.search_volume = data.volume
    topic.keyword_difficulty = data.difficulty
    topic.search_market = f"{cfg.search_country}/{cfg.search_language}"
    topic.search_status = BlogTopic.SearchStatus.READY
    topic.search_checked_at = timezone.now()


SEARCH_FIELDS = ["keyword_metrics", "primary_keyword", "search_volume", "keyword_difficulty", "search_market",
                 "search_status", "search_checked_at", "updated_at"]
