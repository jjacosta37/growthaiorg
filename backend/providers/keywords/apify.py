"""KeywordSource backed by the keywordlab/keyword-search-volume Apify actor.

The actor reads DataForSEO's Google keyword database: average monthly volume and a 0-100
difficulty score. It charges per keyword that has data, and lists the keywords without data in
the run's SUMMARY record. Verified against a live run on 2026-10-13.
"""

import logging
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any

from llm.tracing import trace_tool
from providers.apify_runs import settled_run

from .base import KeywordLookupResult, KeywordMetrics, KeywordQuery, is_lookup_keyword, normalize_keyword

log = logging.getLogger(__name__)


def map_item(item: dict) -> tuple[str, KeywordMetrics] | None:
    """One dataset item as (normalised keyword, metrics), or None if it has no keyword."""
    keyword = normalize_keyword(str(item.get("keyword") or ""))
    if not keyword:
        return None
    difficulty = item.get("keyword_difficulty")
    return keyword, KeywordMetrics(
        volume=max(0, int(item.get("search_volume") or 0)),
        difficulty=None if difficulty is None else max(0, min(100, int(difficulty))),
    )


class ApifyKeywordSource:
    """KeywordSource that runs the keyword actor once per lookup."""

    name = "apify"

    def __init__(self, token: str, actor_id: str = "keywordlab/keyword-search-volume", *, timeout_minutes: int = 5,
                 max_charge_usd: Decimal | None = None, client: Any = None):
        if client is None:
            from apify_client import ApifyClient

            client = ApifyClient(token)
        self.client = client
        self.actor_id = actor_id
        self.timeout = timedelta(minutes=timeout_minutes)
        self.max_charge_usd = max_charge_usd

    def build_input(self, query: KeywordQuery) -> dict:
        """The actor input: normalised, deduplicated keywords within the actor's limits."""
        keywords = list(dict.fromkeys(normalize_keyword(k) for k in query.keywords if is_lookup_keyword(k)))
        return {"keywords": keywords, "country": query.country, "language": query.language,
                "liveLookupForMissing": False}

    def lookup(self, query: KeywordQuery) -> KeywordLookupResult:
        """Look up every valid keyword in one actor run. Never raises."""
        result = KeywordLookupResult(provider=self.name, resource_id=self.actor_id)
        run_input = self.build_input(query)
        if not run_input["keywords"]:
            return result
        with trace_tool(
            "apify.keyword_lookup",
            inputs={"keywords": len(run_input["keywords"]), "country": query.country, "language": query.language},
            metadata={"actor_id": self.actor_id},
        ) as outputs:
            self._lookup(run_input, result)
            outputs.update(apify_run_id=result.external_run_id, status=result.status, items_raw=result.items_raw,
                           with_data=len(result.metrics), without_data=len(result.without_data),
                           cost_usd=float(result.cost_usd), duration_ms=result.duration_ms, error=result.error)
        return result

    def _lookup(self, run_input: dict, result: KeywordLookupResult) -> None:
        """Run the actor and fill `result`. Never raises: a failed lookup degrades to an error
        string, and the pipeline keeps the topics pending for a later run."""
        started = time.monotonic()
        try:
            run = self.client.actor(self.actor_id).call(run_input=run_input, run_timeout=self.timeout,
                                                        max_total_charge_usd=self.max_charge_usd)
        except Exception as exc:  # network/auth/actor failure: surface it on the run
            result.duration_ms = int((time.monotonic() - started) * 1000)
            log.warning("apify keyword lookup failed: %s", exc, exc_info=True)
            result.error = f"{type(exc).__name__}: {exc}"
            return
        if run is None:
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.status = "TIMED-OUT"
            result.error = "Apify run did not finish in time"
            return
        run = settled_run(self.client, run)
        result.external_run_id = run.id or ""
        result.status = run.status or ""
        result.cost_usd = Decimal(str(run.usage_total_usd or 0))
        if run.status != "SUCCEEDED":
            result.error = f"Apify run {run.id} ended with status {run.status}"
        for item in self.client.dataset(run.default_dataset_id).iterate_items():
            result.items_raw += 1
            if mapped := map_item(item):
                result.metrics[mapped[0]] = mapped[1]
        if not result.error:
            # Only a finished run's "no data" is an answer; a failed run's is just missing.
            looked_up = set(run_input["keywords"])
            result.without_data = sorted(looked_up - set(result.metrics))
        result.duration_ms = int((time.monotonic() - started) * 1000)
