import httpx
import pytest

from providers.crawl.crawler import Crawler
from providers.crawl.http import BlockedAddress

BODY = "<p>" + ("Acme helps small teams plan projects and hit their deadlines. " * 8) + "</p>"


def page(title, extra=""):
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1>{BODY}{extra}</main></body></html>"


def public_dns(host, port, **kwargs):
    """Resolves every name to a public address, like a real site on the internet."""
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def make_crawler(routes: dict[str, tuple[int, str, str]], resolve=public_dns):
    """routes: url -> (status, content_type, body), or (3xx, "redirect", location). Unknown URLs 404.

    The client doesn't follow redirects, matching `guarded_client`: the crawler does that itself.
    """
    requested = []

    def handler(request: httpx.Request):
        url = str(request.url)
        requested.append(url)
        status, ctype, body = routes.get(url, (404, "text/plain", "nope"))
        if ctype == "redirect":
            return httpx.Response(status, headers={"location": body})
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return Crawler(client=client, delay_seconds=0, resolve=resolve), requested


HTML = "text/html; charset=utf-8"
XML = "application/xml"


def test_sitemap_index_crawl_respects_robots_limit_and_skips():
    routes = {
        "https://acme.example/robots.txt": (200, "text/plain",
                                          "User-agent: *\nDisallow: /private\nSitemap: https://acme.example/idx.xml"),
        "https://acme.example/idx.xml": (200, XML, """<sitemapindex>
            <sitemap><loc>https://acme.example/pages.xml</loc></sitemap></sitemapindex>"""),
        "https://acme.example/pages.xml": (200, XML, """<urlset>
            <url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/pricing</loc></url>
            <url><loc>https://acme.example/private/admin</loc></url>
            <url><loc>https://acme.example/empty</loc></url>
            <url><loc>https://acme.example/features/deep/page</loc></url>
            <url><loc>https://acme.example/broken</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/pricing": (200, HTML, page("Pricing")),
        "https://acme.example/empty": (200, HTML, "<html><body><div id=root></div></body></html>"),
        "https://acme.example/features/deep/page": (200, HTML, page("Deep")),
    }
    crawler, requested = make_crawler(routes)
    progress = []

    result = crawler.crawl("https://acme.example", max_pages=5,
                           progress=lambda msg, **data: progress.append(msg))

    assert result.discovery == "sitemap"
    assert result.discovered == 6
    assert [p.title for p in result.pages] == ["Home", "Pricing"]
    reasons = dict(result.skipped)
    assert reasons["https://acme.example/private/admin"] == "robots.txt"
    assert reasons["https://acme.example/empty"] == "too little text"
    assert reasons["https://acme.example/broken"] == "HTTP 404"
    assert "https://acme.example/private/admin" not in requested  # never fetched
    assert "https://acme.example/features/deep/page" not in requested  # deepest page cut by max_pages=5
    assert any("Found 6 pages" in m for m in progress)


def test_falls_back_to_links_without_sitemap():
    home = page("Home", '<a href="/about">About</a> <a href="/app.js">js</a> <a href="https://other.example/">o</a>')
    routes = {
        "https://acme.example/": (200, HTML, home),
        "https://acme.example/about": (200, HTML, page("About", '<a href="/">home</a> <a href="/team">t</a>')),
        "https://acme.example/team": (200, HTML, page("Team")),
    }
    crawler, requested = make_crawler(routes)

    result = crawler.crawl("https://acme.example/", max_pages=2)

    assert result.discovery == "links"
    assert [p.title for p in result.pages] == ["Home", "About"]
    assert not any("other.example" in u or u.endswith(".js") for u in requested)
    assert "https://acme.example/team" not in requested  # page budget reached


def test_non_html_is_skipped():
    routes = {
        "https://acme.example/sitemap.xml": (200, XML,
                                           "<urlset><url><loc>https://acme.example/report</loc></url></urlset>"),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/report": (200, "application/pdf", "%PDF"),
    }
    crawler, _ = make_crawler(routes)
    result = crawler.crawl("https://acme.example", max_pages=10)
    assert [p.title for p in result.pages] == ["Home"]
    assert ("https://acme.example/report", "not HTML") in result.skipped


SPA = ('<html><head><title>Pricing | OW</title><meta name="description" content="One plan, everything included.">'
       '</head><body><div id="root"></div></body></html>')


class FakeRenderer:
    name = "fake"

    def __init__(self, texts):
        self.texts = texts
        self.requested = None

    def render(self, urls):
        from decimal import Decimal

        from providers.crawl import RenderedPage, RenderResult

        self.requested = urls
        pages = [RenderedPage(url=u + "/", title="Pricing", text=self.texts[u]) for u in urls if u in self.texts]
        return RenderResult(pages=pages, provider="fake", external_run_id="run1", cost_usd=Decimal("0.02"))


def _spa_routes():
    return {
        "https://acme.example/sitemap.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/pricing</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/pricing": (200, HTML, SPA),
    }


def test_thin_pages_keep_meta_without_renderer():
    crawler, _ = make_crawler(_spa_routes())
    result = crawler.crawl("https://acme.example", max_pages=10)
    pricing = next(p for p in result.pages if p.url.endswith("/pricing"))
    assert pricing.thin and "One plan, everything included." in pricing.text
    assert result.render is None


def test_thin_pages_are_rendered():
    crawler, _ = make_crawler(_spa_routes())
    renderer = FakeRenderer({"https://acme.example/pricing": "Pricing. One plan at $9/month. " * 20})
    result = crawler.crawl("https://acme.example", max_pages=10, renderer=renderer)
    assert renderer.requested == ["https://acme.example/pricing"]  # only the thin page
    pricing = next(p for p in result.pages if p.url.endswith("/pricing"))
    assert pricing.rendered and not pricing.thin and "$9/month" in pricing.text  # matched despite trailing slash
    assert result.thin_pages == []


# --- SSRF: the crawl never leaves the site or reaches a private address (patterns §6) ------

def test_redirect_to_another_host_is_not_followed():
    routes = {
        "https://acme.example/sitemap.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/old</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/old": (302, "redirect", "http://10.0.0.5/admin"),
    }
    crawler, requested = make_crawler(routes)

    result = crawler.crawl("https://acme.example", max_pages=10)

    assert ("https://acme.example/old", "redirected off-site") in result.skipped
    assert not any("10.0.0.5" in u for u in requested)
    assert [p.title for p in result.pages] == ["Home"]


def test_same_site_redirect_is_followed_and_stored_under_the_final_url():
    routes = {
        "https://acme.example/sitemap.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/old</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/old": (301, "redirect", "/new"),
        "https://acme.example/new": (200, HTML, page("New")),
    }
    crawler, _ = make_crawler(routes)

    result = crawler.crawl("https://acme.example", max_pages=10)

    assert [(p.url, p.title) for p in result.pages] == [("https://acme.example/", "Home"),
                                                        ("https://acme.example/new", "New")]


def test_redirect_loops_stop():
    routes = {
        "https://acme.example/sitemap.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/a</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/a": (302, "redirect", "/b"),
        "https://acme.example/b": (302, "redirect", "/a"),
    }
    crawler, _ = make_crawler(routes)

    result = crawler.crawl("https://acme.example", max_pages=10)

    assert ("https://acme.example/a", "too many redirects") in result.skipped


def test_sitemaps_on_other_hosts_are_never_fetched():
    routes = {
        "https://acme.example/robots.txt": (200, "text/plain",
                                          "Sitemap: http://169.254.169.254/latest/meta-data\n"
                                          "Sitemap: https://acme.example/idx.xml"),
        "https://acme.example/idx.xml": (200, XML, """<sitemapindex>
            <sitemap><loc>http://192.168.1.1/sitemap.xml</loc></sitemap>
            <sitemap><loc>https://acme.example/pages.xml</loc></sitemap></sitemapindex>"""),
        "https://acme.example/pages.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/pricing</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/pricing": (200, HTML, page("Pricing")),
    }
    crawler, requested = make_crawler(routes)
    progress = []

    result = crawler.crawl("https://acme.example", max_pages=10, progress=lambda msg, **data: progress.append(data))

    assert all(u.startswith("https://acme.example/") for u in requested)
    assert [p.title for p in result.pages] == ["Home", "Pricing"]
    assert any(d.get("sitemaps_off_site") == 2 for d in progress)


def test_oversized_bodies_are_skipped(monkeypatch):
    monkeypatch.setattr("providers.crawl.crawler.MAX_BYTES", 2000)
    routes = {
        "https://acme.example/sitemap.xml": (200, XML, """<urlset><url><loc>https://acme.example/</loc></url>
            <url><loc>https://acme.example/huge</loc></url></urlset>"""),
        "https://acme.example/": (200, HTML, page("Home")),
        "https://acme.example/huge": (200, HTML, page("Huge", "x" * 5000)),
    }
    crawler, _ = make_crawler(routes)

    result = crawler.crawl("https://acme.example", max_pages=10)

    assert ("https://acme.example/huge", "too large") in result.skipped
    assert [p.title for p in result.pages] == ["Home"]


def test_blocked_connections_are_reported_as_blocked():
    def handler(request):
        if request.url.path == "/inside":
            raise httpx.ConnectError("blocked") from BlockedAddress("acme.example")
        if request.url.path == "/down":
            raise httpx.ConnectError("refused")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": XML}, text="""<urlset>
                <url><loc>https://acme.example/</loc></url><url><loc>https://acme.example/inside</loc></url>
                <url><loc>https://acme.example/down</loc></url></urlset>""")
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": HTML}, text=page("Home"))
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    crawler = Crawler(client=client, delay_seconds=0, resolve=public_dns)

    result = crawler.crawl("https://acme.example", max_pages=10)

    reasons = dict(result.skipped)
    assert reasons["https://acme.example/inside"] == "blocked address"
    assert reasons["https://acme.example/down"] == "unreachable"


@pytest.mark.parametrize("url", ["http://10.0.0.5", "http://192.168.1.1/", "http://[::1]:8000"])
def test_private_start_address_fails_before_any_request(url):
    crawler, requested = make_crawler({})

    with pytest.raises(ValueError, match="as a public website"):
        crawler.crawl(url, max_pages=10)
    assert requested == []


def test_public_name_resolving_privately_fails_before_any_request():
    crawler, requested = make_crawler({}, resolve=lambda host, port, **kw: [(2, 1, 6, "", ("192.168.1.20", port))])

    with pytest.raises(ValueError, match="as a public website"):
        crawler.crawl("https://intranet.acme.example", max_pages=10)
    assert requested == []


def test_unknown_and_private_hosts_fail_with_the_same_message():
    """Different messages would let a tenant probe which names exist on the operator's LAN."""
    def nxdomain(host, port, **kwargs):
        raise OSError("Name or service not known")

    def private(host, port, **kwargs):
        return [(2, 1, 6, "", ("192.168.1.20", port))]

    messages = []
    for resolve in (nxdomain, private):
        crawler, _ = make_crawler({}, resolve=resolve)
        with pytest.raises(ValueError) as exc_info:
            crawler.crawl("https://nas.example", max_pages=10)
        messages.append(str(exc_info.value))
    assert messages[0] == messages[1]


def test_malformed_link_host_skips_the_link_without_aborting_the_crawl():
    home = page("Home", '<a href="http://0177.0.0.1/x">bad</a> <a href="/about">About</a>')
    routes = {
        "https://acme.example/": (200, HTML, home),
        "https://acme.example/about": (200, HTML, page("About")),
    }
    crawler, _ = make_crawler(routes)

    result = crawler.crawl("https://acme.example/", max_pages=5)

    assert [p.title for p in result.pages] == ["Home", "About"]


def test_renderer_only_gets_same_site_urls():
    from providers.crawl.crawler import CrawledPageData, CrawlResult

    crawler, _ = make_crawler({})
    crawler.root = "https://acme.example"
    result = CrawlResult(root_url="https://acme.example/", discovery="sitemap", pages=[
        CrawledPageData(url="https://acme.example/pricing", title="", text="", thin=True),
        CrawledPageData(url="http://10.0.0.5/admin", title="", text="", thin=True),
    ])
    renderer = FakeRenderer({})

    crawler._render_thin_pages(result, renderer, lambda msg, **data: None)

    assert renderer.requested == ["https://acme.example/pricing"]
