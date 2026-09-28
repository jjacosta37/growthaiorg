import httpx

from providers.crawl.crawler import Crawler

BODY = "<p>" + ("Acme helps small teams plan projects and hit their deadlines. " * 8) + "</p>"


def page(title, extra=""):
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1>{BODY}{extra}</main></body></html>"


def make_crawler(routes: dict[str, tuple[int, str, str]]):
    """routes: url -> (status, content_type, body). Unknown URLs 404."""
    requested = []

    def handler(request: httpx.Request):
        url = str(request.url)
        requested.append(url)
        status, ctype, body = routes.get(url, (404, "text/plain", "nope"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Crawler(client=client, delay_seconds=0), requested


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
