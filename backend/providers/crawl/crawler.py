"""Website crawler for onboarding: sitemap first, link-following (BFS) as a fallback.

Polite by default: honors robots.txt for our user agent, one request at a time, bounded
page count and response size. Pages that come back thin (JavaScript-rendered) keep their
title/meta description and, if a PageRenderer is provided, are re-fetched with a real browser.

Safe by construction (docs/security-patterns.md §6): requests go through `guarded_client`,
which only connects to public addresses, and the crawl never leaves the site it started on.
Sitemaps, redirects and the pages sent to the renderer all have to be same-site.
"""

import logging
import socket
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from .extract import extract_links, extract_text
from .http import USER_AGENT, BlockedAddress, Resolver, guarded_client, resolve_public
from .render import PageRenderer, RenderResult
from .sitemap import parse_sitemap, sitemaps_from_robots
from .urls import is_crawlable, normalize, prioritize, same_site

log = logging.getLogger(__name__)

MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
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


# Takes a message plus arbitrary structured detail, which the pipeline passes straight
# through to RunReporter.step as RunEvent.data.
ProgressFn = Callable[..., None]


class Crawler:
    """Crawls one website, staying on it.

    Args:
        client: an httpx client that doesn't follow redirects itself. Defaults to
            `guarded_client`; tests pass one with a mock transport.
        delay_seconds: pause between page requests.
        resolve: DNS resolver for the start-host check (a `socket.getaddrinfo` stand-in).
    """

    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.2,
                 resolve: Resolver = socket.getaddrinfo):
        self.client = client or guarded_client(resolve)
        self.delay = delay_seconds
        self.resolve = resolve
        self.robots: robotparser.RobotFileParser | None = None
        self.root = ""
        self.sitemaps_off_site = 0

    # -- HTTP -----------------------------------------------------------------
    def _get(self, url: str) -> tuple[httpx.Response | None, str]:
        """GET `url`, following same-site redirects, with the body capped at MAX_BYTES.

        Returns the buffered response and "", or None and the reason it was skipped.
        """
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with self.client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        location = normalize(resp.headers.get("location", ""), base=url)
                        if not location or not same_site(location, self.root):
                            log.info("crawl: %s redirects off-site, not followed", url)
                            return None, "redirected off-site"
                        url = location
                        continue
                    return self._read_capped(resp, url)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:  # InvalidURL: a malformed link host
                reason = "blocked address" if isinstance(exc.__cause__, BlockedAddress) else "unreachable"
                log.info("crawl: GET %s failed (%s): %s", url, reason, type(exc).__name__)
                return None, reason
        log.info("crawl: %s took more than %s redirects", url, MAX_REDIRECTS)
        return None, "too many redirects"

    def _read_capped(self, resp: httpx.Response, url: str) -> tuple[httpx.Response | None, str]:
        """Read a streamed body, giving up as soon as it passes MAX_BYTES (decompressed)."""
        try:
            declared = int(resp.headers.get("content-length", "0"))
        except ValueError:
            declared = 0
        if declared > MAX_BYTES:
            log.info("crawl: skipping %s, declares %s bytes, over the %s limit", url, declared, MAX_BYTES)
            return None, "too large"
        body = bytearray()
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) > MAX_BYTES:
                log.info("crawl: skipping %s, over the %s byte limit", url, MAX_BYTES)
                return None, "too large"
        # The body is already decoded, so the encoding headers no longer describe it.
        headers = [(k, v) for k, v in resp.headers.multi_items()
                   if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        return httpx.Response(resp.status_code, headers=headers, content=bytes(body), request=resp.request), ""

    def _allowed(self, url: str) -> bool:
        return self.robots.can_fetch(USER_AGENT, url) if self.robots else True

    # -- Discovery ------------------------------------------------------------
    def _load_robots(self, root: str) -> list[str]:
        self.robots = robotparser.RobotFileParser()
        resp, _ = self._get(f"{root}/robots.txt")
        if resp is None or resp.status_code >= 400:
            self.robots.parse([])
            return []
        text = resp.text
        self.robots.parse(text.splitlines())
        return sitemaps_from_robots(text)

    def discover_from_sitemaps(self, root: str, candidates: list[str]) -> list[str]:
        """Page URLs from the site's sitemaps. Sitemaps on other hosts are never fetched."""
        candidates = candidates or [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"]
        queue = deque(u for u in candidates if same_site(u, root))
        self.sitemaps_off_site = len(candidates) - len(queue)
        seen: set[str] = set()
        urls: list[str] = []
        while queue and len(seen) < MAX_SITEMAPS:
            sm = queue.popleft()
            if sm in seen:
                continue
            seen.add(sm)
            resp, _ = self._get(sm)
            if resp is None or resp.status_code >= 400:
                continue
            doc = parse_sitemap(resp.content)
            urls.extend(doc.page_urls)
            children = [u for u in doc.child_sitemaps if same_site(u, root)]
            self.sitemaps_off_site += len(doc.child_sitemaps) - len(children)
            queue.extend(children)
        return urls

    # -- Crawl ----------------------------------------------------------------
    def crawl(self, website_url: str, max_pages: int, progress: ProgressFn | None = None,
              renderer: PageRenderer | None = None) -> CrawlResult:
        """Crawl `website_url`: sitemap pages if there are any, else links from the homepage.

        Raises:
            ValueError: the URL isn't usable, or its host isn't a public website.
        """
        progress = progress or (lambda msg, **data: None)
        start = normalize(website_url)
        if not start:
            raise ValueError(f"Not a valid website URL: {website_url!r}")
        p = urlparse(start)
        root = f"{p.scheme}://{p.netloc}"
        self._check_start_host(p.hostname or "", p.port or (443 if p.scheme == "https" else 80))
        self.root = root

        progress("Reading robots.txt and sitemap")
        sitemap_urls = self.discover_from_sitemaps(root, self._load_robots(root))
        candidates = prioritize([start, *sitemap_urls], root, max_pages)
        if len(candidates) > 1:
            result = CrawlResult(root_url=start, discovery="sitemap", discovered=len(set(sitemap_urls)))
            progress(f"Found {result.discovered} pages in the sitemap; crawling {len(candidates)}",
                     discovered=result.discovered, crawling=len(candidates), discovery="sitemap",
                     sitemaps_off_site=self.sitemaps_off_site)
            for i, url in enumerate(candidates, 1):
                self._fetch_page(url, result)
                if i % 5 == 0:
                    progress(f"Crawled {i}/{len(candidates)} pages", crawled=i, total=len(candidates))
                self._sleep()
        else:
            result = CrawlResult(root_url=start, discovery="links")
            progress("No usable sitemap; following links from the homepage", discovery="links",
                     sitemaps_off_site=self.sitemaps_off_site)
            self._crawl_links(start, root, max_pages, result, progress)
        if renderer is not None and result.thin_pages:
            self._render_thin_pages(result, renderer, progress)
        return result

    def _check_start_host(self, host: str, port: int) -> None:
        """Fail the crawl up front, with a clear message, when the site isn't on the public internet.

        One message for "doesn't resolve" and "resolves privately": telling them apart would let
        a tenant probe which hostnames exist on the operator's network.

        Raises:
            ValueError: the host doesn't resolve, or resolves to a private or local address.
        """
        try:
            resolve_public(host, port, self.resolve)
        except BlockedAddress:
            raise ValueError(f"Couldn't reach {host} as a public website. Check the address.") from None

    def _render_thin_pages(self, result: CrawlResult, renderer: PageRenderer, progress: ProgressFn) -> None:
        # Same-site by construction; checked again because these URLs are fetched by a third party.
        thin = [p for p in result.thin_pages if same_site(p.url, self.root)]
        progress(f"Rendering {len(thin)} JavaScript page(s) with a browser ({renderer.name})",
                 thin_pages=len(thin), renderer=renderer.name)
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
                progress(f"Crawled {len(result.pages)} pages, {len(queue)} links queued",
                         crawled=len(result.pages), queued=len(queue), visited=visited)
            self._sleep()
        result.discovered = len(seen)

    def _fetch_page(self, url: str, result: CrawlResult) -> str | None:
        if not self._allowed(url):
            result.skipped.append((url, "robots.txt"))
            return None
        resp, reason = self._get(url)
        if resp is None:
            result.skipped.append((url, reason))
            return None
        if resp.status_code >= 400:
            result.skipped.append((url, f"HTTP {resp.status_code}"))
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
