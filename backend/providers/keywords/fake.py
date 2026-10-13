"""Deterministic KeywordSource for tests and for local dev without Apify (KEYWORD_SOURCE=fake)."""

from .base import KeywordLookupResult, KeywordMetrics, KeywordQuery, normalize_keyword


class FakeKeywordSource:
    """In-memory KeywordSource: no network, no spend."""

    name = "fake"

    def __init__(self, metrics: dict[str, KeywordMetrics] | None = None, error: str = ""):
        """`metrics` maps keywords to what they return; any other keyword has no data. Without
        `metrics`, every keyword gets a volume and difficulty derived from its length."""
        self.metrics = {normalize_keyword(k): v for k, v in metrics.items()} if metrics is not None else None
        self.error = error
        self.queries: list[KeywordQuery] = []

    def lookup(self, query: KeywordQuery) -> KeywordLookupResult:
        """Answer from `metrics`, or fail with `error` if one was given."""
        self.queries.append(query)
        keywords = list(dict.fromkeys(normalize_keyword(k) for k in query.keywords))
        result = KeywordLookupResult(provider=self.name, status="FAILED" if self.error else "SUCCEEDED",
                                     duration_ms=1, error=self.error)
        if self.error:
            return result
        for k in keywords:
            m = self.metrics.get(k) if self.metrics is not None else KeywordMetrics(len(k) * 10, len(k) % 100)
            if m is None:
                result.without_data.append(k)
            else:
                result.metrics[k] = m
        result.items_raw = len(result.metrics)
        return result
