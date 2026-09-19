"""Rendering JavaScript-only pages. Our crawler handles server-rendered HTML; pages that come back
thin (client-rendered SPAs) are handed to a PageRenderer, which runs a real browser."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

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
    external_id: str = ""
    cost_usd: Decimal = Decimal(0)
    error: str = ""


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
        try:
            run = self.client.actor(self.actor_id).call(run_input=self.build_input(urls), run_timeout=self.timeout)
        except Exception as exc:  # network/auth/actor errors: degrade to unrendered pages
            log.warning("apify render failed: %s", exc)
            result.error = f"{type(exc).__name__}: {exc}"
            return result
        if run is None:
            result.error = "Apify run did not finish in time"
            return result
        result.external_id = run.id or ""
        result.cost_usd = Decimal(str(run.usage_total_usd or 0))
        if run.status != "SUCCEEDED":
            result.error = f"Apify run {run.id} ended with status {run.status}"
        for item in self.client.dataset(run.default_dataset_id).iterate_items():
            text = (item.get("markdown") or item.get("text") or "").strip()
            meta = item.get("metadata") or {}
            url = item.get("url") or (item.get("crawl") or {}).get("loadedUrl") or ""
            if url and text:
                result.pages.append(RenderedPage(url=url, title=(meta.get("title") or "").strip(), text=text))
        return result
