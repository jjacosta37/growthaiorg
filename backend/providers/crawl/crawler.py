"""Website crawler for onboarding: sitemap first, link-following (BFS) as a fallback.

Polite by default: honors robots.txt for our user agent, one request at a time, bounded
page count and response size. Pages that come back thin (JavaScript-rendered) keep their
title/meta description and, if a PageRenderer is provided, are re-fetched with a real browser.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from .extract import extract_links, extract_text
from .render import PageRenderer, RenderResult
from .sitemap import parse_sitemap, sitemaps_from_robots
from .urls import is_crawlable, normalize, prioritize, same_site

log = logging.getLogger(__name__)

USER_AGENT = "SiftBot/0.1 (internal content assistant)"
MAX_BYTES = 3_000_000
MAX_SITEMAPS = 20
MIN_TEXT_CHARS = 200  # less extracted text than this marks a page "thin" (likely JavaScript-rendered)


@dataclass
class CrawledPageData:
    url: str
    title: str
    text: str
    thin: bool = False  # only title/meta description; the real content needs a browser
    rendered: bool = False  # text came from the PageRenderer


@dataclass
class CrawlResult:
    root_url: str
    discovery: str  # "sitemap" | "links"
    discovered: int = 0
    pages: list[CrawledPageData] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (url, reason)
    render: RenderResult | None = None

    @property
    def thin_pages(self) -> list[CrawledPageData]:
        return [p for p in self.pages if p.thin]


ProgressFn = Callable[[str], None]


class Crawler:
    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.2):
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=15.0, follow_redirects=True
        )
        self.delay = delay_seconds
        self.robots: robotparser.RobotFileParser | None = None

    # -- HTTP -----------------------------------------------------------------
    def _get(self, url: str) -> httpx.Response | None:
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as exc:
            log.info("crawl: GET %s failed: %s", url, exc)
            return None
        if len(resp.content) > MAX_BYTES:
            return None
        return resp

    def _allowed(self, url: str) -> bool:
        return self.robots.can_fetch(USER_AGENT, url) if self.robots else True

    # -- Discovery ------------------------------------------------------------
    def _load_robots(self, root: str) -> list[str]:
        self.robots = robotparser.RobotFileParser()
        resp = self._get(f"{root}/robots.txt")
        if resp is None or resp.status_code >= 400:
            self.robots.parse([])
            return []
        text = resp.text
        self.robots.parse(text.splitlines())
        return sitemaps_from_robots(text)

    def discover_from_sitemaps(self, root: str, candidates: list[str]) -> list[str]:
        queue = deque(candidates or [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"])
        seen: set[str] = set()
        urls: list[str] = []
        while queue and len(seen) < MAX_SITEMAPS:
            sm = queue.popleft()
            if sm in seen:
                continue
            seen.add(sm)
            resp = self._get(sm)
            if resp is None or resp.status_code >= 400:
                continue
            doc = parse_sitemap(resp.content)
            urls.extend(doc.page_urls)
            queue.extend(doc.child_sitemaps)
        return urls

    # -- Crawl ----------------------------------------------------------------
    def crawl(self, website_url: str, max_pages: int, progress: ProgressFn | None = None,
              renderer: PageRenderer | None = None) -> CrawlResult:
        progress = progress or (lambda msg: None)
        start = normalize(website_url)
        if not start:
            raise ValueError(f"Not a valid website URL: {website_url!r}")
        p = urlparse(start)
        root = f"{p.scheme}://{p.netloc}"

        progress("Reading robots.txt and sitemap")
        sitemap_urls = self.discover_from_sitemaps(root, self._load_robots(root))
        candidates = prioritize([start, *sitemap_urls], root, max_pages)
        if len(candidates) > 1:
            result = CrawlResult(root_url=start, discovery="sitemap", discovered=len(set(sitemap_urls)))
            progress(f"Found {result.discovered} pages in the sitemap; crawling {len(candidates)}")
            for i, url in enumerate(candidates, 1):
                self._fetch_page(url, result)
                if i % 5 == 0:
                    progress(f"Crawled {i}/{len(candidates)} pages")
                self._sleep()
        else:
            result = CrawlResult(root_url=start, discovery="links")
            progress("No usable sitemap; following links from the homepage")
            self._crawl_links(start, root, max_pages, result, progress)
        if renderer is not None and result.thin_pages:
            self._render_thin_pages(result, renderer, progress)
        return result

    def _render_thin_pages(self, result: CrawlResult, renderer: PageRenderer, progress: ProgressFn) -> None:
        thin = result.thin_pages
        progress(f"Rendering {len(thin)} JavaScript page(s) with a browser ({renderer.name})")
        rendered = renderer.render([p.url for p in thin])
        result.render = rendered
        by_url = {normalize(r.url): r for r in rendered.pages}
        for page in thin:
            r = by_url.get(page.url)
            if r and len(r.text) > len(page.text):
                page.text = r.text
                page.title = r.title or page.title
                page.thin = False
                page.rendered = True

    def _crawl_links(self, start, root, max_pages, result: CrawlResult, progress: ProgressFn) -> None:
        queue = deque([start])
        seen = {start}
        visited = 0
        # Visit at most 3x the page budget, so link-heavy pages with little text can't loop forever.
        while queue and len(result.pages) < max_pages and visited < max_pages * 3:
            url = queue.popleft()
            visited += 1
            html = self._fetch_page(url, result)
            if html:
                for link in extract_links(html, url):
                    if link not in seen and same_site(link, root) and is_crawlable(link):
                        seen.add(link)
                        queue.append(link)
            if visited % 5 == 0:
                progress(f"Crawled {len(result.pages)} pages, {len(queue)} links queued")
            self._sleep()
        result.discovered = len(seen)

    def _fetch_page(self, url: str, result: CrawlResult) -> str | None:
        if not self._allowed(url):
            result.skipped.append((url, "robots.txt"))
            return None
        resp = self._get(url)
        if resp is None or resp.status_code >= 400:
            result.skipped.append((url, f"HTTP {resp.status_code if resp is not None else 'error'}"))
            return None
        if "html" not in resp.headers.get("content-type", ""):
            result.skipped.append((url, "not HTML"))
            return None
        final_url = normalize(str(resp.url)) or url
        html = resp.text
        if any(p.url == final_url for p in result.pages):
            return html
        extracted = extract_text(html, final_url)
        if len(extracted.text) >= MIN_TEXT_CHARS:
            result.pages.append(CrawledPageData(url=final_url, title=extracted.title, text=extracted.text))
        elif extracted.description or extracted.title:
            # Keep what the server did send; a renderer may fill in the rest.
            fallback = "\n\n".join(x for x in (extracted.title, extracted.description, extracted.text) if x)
            result.pages.append(CrawledPageData(url=final_url, title=extracted.title, text=fallback, thin=True))
        else:
            result.skipped.append((url, "too little text"))
        return html

    def _sleep(self) -> None:
        if self.delay:
            time.sleep(self.delay)


def crawl_site(website_url: str, max_pages: int, progress: ProgressFn | None = None,
               delay_seconds: float = 0.2, renderer: PageRenderer | None = None) -> CrawlResult:
    """Entry point used by the onboarding pipeline."""
    return Crawler(delay_seconds=delay_seconds).crawl(website_url, max_pages, progress, renderer)
