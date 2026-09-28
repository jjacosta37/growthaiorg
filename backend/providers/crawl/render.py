"""Rendering JavaScript-only pages. Our crawler handles server-rendered HTML; pages that come back
thin (client-rendered SPAs) are handed to a PageRenderer, which runs a real browser."""

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from llm.tracing import trace_tool

log = logging.getLogger(__name__)


@dataclass
class RenderedPage:
    url: str
    title: str
    text: str


@dataclass
class RenderResult:
    pages: list[RenderedPage] = field(default_factory=list)
    provider: str = ""
    external_run_id: str = ""
    cost_usd: Decimal = Decimal(0)
    error: str = ""
    # Reported on the run, same shape as RedditSearchResult so one helper records both.
    status: str = ""
    duration_ms: int = 0
    items_raw: int = 0


class PageRenderer(Protocol):
    name: str

    def render(self, urls: list[str]) -> RenderResult: ...


class ApifyRenderer:
    """Apify's Website Content Crawler with a real browser, limited to exactly the given URLs."""

    name = "apify"

    def __init__(self, token: str, actor_id: str = "apify/website-content-crawler", *,
                 timeout_minutes: int = 10, client=None):
        if client is None:
            from apify_client import ApifyClient

            client = ApifyClient(token)
        self.client = client
        self.actor_id = actor_id
        self.timeout = timedelta(minutes=timeout_minutes)

    def build_input(self, urls: list[str]) -> dict:
        return {
            "startUrls": [{"url": u} for u in urls],
            "crawlerType": "playwright:firefox",
            "maxCrawlDepth": 0,  # only these URLs, don't follow links
            "maxCrawlPages": len(urls),
            "maxResults": len(urls),
            "useSitemaps": False,
            "respectRobotsTxtFile": True,
            "saveMarkdown": True,
            "htmlTransformer": "readableText",
        }

    def render(self, urls: list[str]) -> RenderResult:
        result = RenderResult(provider=self.name)
        if not urls:
            return result
        with trace_tool("apify.render_pages", inputs={"urls": urls},
                        metadata={"actor_id": self.actor_id}) as outputs:
            self._render(urls, result)
            outputs.update(apify_run_id=result.external_run_id, status=result.status,
                           items_raw=result.items_raw, pages=len(result.pages),
                           cost_usd=float(result.cost_usd), duration_ms=result.duration_ms,
                           error=result.error)
        return result

    def _render(self, urls: list[str], result: RenderResult) -> None:
        """Run the actor and fill `result`. Never raises: rendering is best-effort, and a
        failure degrades to unrendered pages rather than taking the crawl down."""
        started = time.monotonic()
        try:
            run = self.client.actor(self.actor_id).call(run_input=self.build_input(urls), run_timeout=self.timeout)
        except Exception as exc:  # network/auth/actor errors: degrade to unrendered pages
            result.duration_ms = int((time.monotonic() - started) * 1000)
            log.warning("apify render failed: %s", exc, exc_info=True)
            result.error = f"{type(exc).__name__}: {exc}"
            return
        if run is None:
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.status = "TIMED-OUT"
            result.error = "Apify run did not finish in time"
            return
        result.external_run_id = run.id or ""
        result.status = run.status or ""
        result.cost_usd = Decimal(str(run.usage_total_usd or 0))
        if run.status != "SUCCEEDED":
            result.error = f"Apify run {run.id} ended with status {run.status}"
        for item in self.client.dataset(run.default_dataset_id).iterate_items():
            result.items_raw += 1
            text = (item.get("markdown") or item.get("text") or "").strip()
            meta = item.get("metadata") or {}
            url = item.get("url") or (item.get("crawl") or {}).get("loadedUrl") or ""
            if url and text:
                result.pages.append(RenderedPage(url=url, title=(meta.get("title") or "").strip(), text=text))
        result.duration_ms = int((time.monotonic() - started) * 1000)
