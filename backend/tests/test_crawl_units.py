from providers.crawl.extract import extract_links, extract_text
from providers.crawl.sitemap import parse_sitemap, sitemaps_from_robots
from providers.crawl.urls import normalize, prioritize

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.example/</loc></url>
  <url><loc> https://acme.example/pricing </loc></url>
  <url><lastmod>2026-01-01</lastmod></url>
</urlset>"""

INDEX = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.example/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://acme.example/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_and_index():
    doc = parse_sitemap(URLSET)
    assert doc.page_urls == ["https://acme.example/", "https://acme.example/pricing"]
    assert doc.child_sitemaps == []

    idx = parse_sitemap(INDEX)
    assert idx.child_sitemaps == ["https://acme.example/sitemap-pages.xml", "https://acme.example/sitemap-blog.xml"]


def test_parse_garbage_returns_empty():
    assert parse_sitemap(b"<html>not a sitemap").page_urls == []
    assert parse_sitemap(b"").page_urls == []


def test_parse_sitemap_does_not_resolve_entities():
    xxe = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
    <urlset><url><loc>&e;</loc></url></urlset>"""
    assert all("root:" not in u for u in parse_sitemap(xxe).page_urls)


def test_sitemaps_from_robots():
    robots = "User-agent: *\nDisallow: /admin\nSitemap: https://acme.example/sm.xml\nsitemap:https://acme.example/b.xml\n"
    assert sitemaps_from_robots(robots) == ["https://acme.example/sm.xml", "https://acme.example/b.xml"]


def test_normalize():
    assert normalize("https://ACME.example/Pricing/#plans") == "https://acme.example/Pricing"
    assert normalize("/about", "https://acme.example/x") == "https://acme.example/about"
    assert normalize("mailto:hi@acme.example") is None
    assert normalize("javascript:void(0)") is None


def test_prioritize_filters_and_orders():
    urls = [
        "https://acme.example/blog/2026/01/some-long-post",
        "https://acme.example/pricing",
        "https://www.acme.example/features",  # www counts as same site
        "https://other.example/pricing",  # other host
        "https://acme.example/logo.png",  # asset
        "https://acme.example/tag/productivity",  # listing page
        "https://acme.example/pricing/",  # duplicate after normalization
        "https://acme.example/",
    ]
    assert prioritize(urls, "https://acme.example", limit=3) == [
        "https://acme.example/",
        "https://acme.example/pricing",
        "https://www.acme.example/features",
    ]


ARTICLE = """<html><head><title>Acme – Project tracking for small teams</title></head><body>
<nav><a href="/pricing">Pricing</a> <a href="https://x.example/">X</a> <a href="#top">Top</a></nav>
<main><h1>See every project at a glance</h1>
<p>Acme brings your team's tasks, deadlines and files together in one board, with owners and
status for every item. It is built for small teams who want clarity.</p>
<p>Connect accounts read-only, then explore exposure by sector, region and asset class.</p></main>
<footer>© 2026</footer></body></html>"""


def test_extract_text_and_links():
    out = extract_text(ARTICLE, "https://acme.example/")
    assert "brings your team's tasks" in out.text
    assert out.title  # trafilatura picks the <title> or the main H1
    links = extract_links(ARTICLE, "https://acme.example/")
    assert "https://acme.example/pricing" in links
    assert "https://x.example/" in links


def _next_page(payload_html: str, description="Guide to sprint planning") -> str:
    """A client-rendered Next.js page: empty DOM, content escaped inside __next_f pushes."""
    import json

    rsc = '5:["$","div",null,{"dangerouslySetInnerHTML":{"__html":' + json.dumps(payload_html) + "}}]\n"
    # Split across two pushes like Next.js does, and keep a raw newline inside the string.
    half = len(rsc) // 2
    parts = (rsc[:half], rsc[half:])
    pushes = "".join(f"<script>self.__next_f.push({json.dumps([1, part])})</script>" for part in parts)
    return (f'<html><head><title>Sprint planning | Acme</title><meta name="description" content="{description}">'
            f'</head><body><div id="root"></div>{pushes}</body></html>')


def test_extracts_nextjs_embedded_html():
    body = "Short sprints make plans easier to adjust. " * 10
    article = f"<h2>What is a sprint?</h2>\n<p>{body}</p>"
    out = extract_text(_next_page(article), "https://acme.example/blog/d")
    assert "Short sprints make plans" in out.text
    assert out.description == "Guide to sprint planning"


def test_client_rendered_page_keeps_title_and_description():
    out = extract_text(_next_page("<span>x</span>"), "https://acme.example/")
    assert out.text == "" or len(out.text) < 50
    assert out.title and out.description == "Guide to sprint planning"


def test_extraction_has_no_cross_call_memory():
    """The same page extracted twice must give the same text (trafilatura's dedup cache is global)."""
    texts = [extract_text(ARTICLE, f"https://acme.example/{i}").text for i in range(6)]
    assert texts[0] and all(t == texts[0] for t in texts)
