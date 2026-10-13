"""Ranking the topic backlog by opportunity: search volume, ease of ranking and Reddit demand,
weighed by the project's settings.

The ranking is computed when the backlog is read rather than stored, so changing a weight
reorders the backlog at once and changes which topic the next run drafts.
"""

import math
from collections.abc import Iterable

from django.db.models import Count, QuerySet

from .config import OpportunityWeights
from .models import BlogTopic

WEIGHT_VALUES = {"off": 0, "low": 1, "medium": 2, "high": 3}
UNKNOWN_EASE = 0.5  # difficulty the provider has no score for counts as middling


def with_evidence_count(qs: QuerySet[BlogTopic]) -> QuerySet[BlogTopic]:
    """Annotate `evidence_count`, which `opportunity()` and the backlog sort read."""
    return qs.annotate(evidence_count=Count("evidence_posts", distinct=True))


def signals(topic: BlogTopic) -> dict[str, float]:
    """Each signal on a comparable scale, strictly increasing in what makes a topic better.

    None of them is capped, so a topic that is better on one signal and equal on the others
    always ranks higher, however large the numbers.
    """
    volume = topic.search_volume or 0
    evidence = getattr(topic, "evidence_count", 0)
    ease = UNKNOWN_EASE if topic.keyword_difficulty is None else (100 - topic.keyword_difficulty) / 100
    return {
        "volume": math.log10(volume + 1) / 5,  # 100k searches/month ≈ 1
        "ease": ease,
        "reddit": evidence / (evidence + 3),  # 3 posts ≈ 0.5, saturating
    }


def opportunity(topic: BlogTopic, weights: OpportunityWeights) -> float | None:
    """The weighted mean of the signals, or None while the topic's search data is pending.

    Returns 0 for every topic when all weights are off, which leaves the order to the date.
    """
    if topic.search_status != BlogTopic.SearchStatus.READY:
        return None
    w = {name: WEIGHT_VALUES[getattr(weights, name)] for name in ("volume", "ease", "reddit")}
    total = sum(w.values())
    if not total:
        return 0.0
    s = signals(topic)
    return sum(w[name] * s[name] for name in w) / total


def rank_topics(topics: Iterable[BlogTopic], weights: OpportunityWeights) -> list[BlogTopic]:
    """The drafting order: topics the user asked for first (oldest first), then topics with
    search data by opportunity, then topics whose search data is still pending (oldest first).

    Args:
        topics: Annotated with `evidence_count` (`with_evidence_count`).
    """
    def key(topic: BlogTopic) -> tuple:
        if topic.requested_by_user:
            return (0, 0.0, topic.created_at)
        score = opportunity(topic, weights)
        if score is None:
            return (2, 0.0, topic.created_at)
        return (1, -score, topic.created_at)

    return sorted(topics, key=key)
