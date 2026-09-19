from providers.crawl.extract import extract_links, extract_text
from providers.crawl.sitemap import parse_sitemap, sitemaps_from_robots
from providers.crawl.urls import normalize, prioritize

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ow.example/</loc></url>
  <url><loc> https://ow.example/pricing </loc></url>
  <url><lastmod>2026-01-01</lastmod></url>
</urlset>"""

INDEX = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://ow.example/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://ow.example/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_and_index():
    doc = parse_sitemap(URLSET)
    assert doc.page_urls == ["https://ow.example/", "https://ow.example/pricing"]
    assert doc.child_sitemaps == []

    idx = parse_sitemap(INDEX)
    assert idx.child_sitemaps == ["https://ow.example/sitemap-pages.xml", "https://ow.example/sitemap-blog.xml"]


def test_parse_garbage_returns_empty():
    assert parse_sitemap(b"<html>not a sitemap").page_urls == []
    assert parse_sitemap(b"").page_urls == []


def test_parse_sitemap_does_not_resolve_entities():
    xxe = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
    <urlset><url><loc>&e;</loc></url></urlset>"""
    assert all("root:" not in u for u in parse_sitemap(xxe).page_urls)


def test_sitemaps_from_robots():
    robots = "User-agent: *\nDisallow: /admin\nSitemap: https://ow.example/sm.xml\nsitemap:https://ow.example/b.xml\n"
    assert sitemaps_from_robots(robots) == ["https://ow.example/sm.xml", "https://ow.example/b.xml"]


def test_normalize():
    assert normalize("https://OW.example/Pricing/#plans") == "https://ow.example/Pricing"
    assert normalize("/about", "https://ow.example/x") == "https://ow.example/about"
    assert normalize("mailto:hi@ow.example") is None
    assert normalize("javascript:void(0)") is None


def test_prioritize_filters_and_orders():
    urls = [
        "https://ow.example/blog/2026/01/some-long-post",
        "https://ow.example/pricing",
        "https://www.ow.example/features",  # www counts as same site
        "https://other.example/pricing",  # other host
        "https://ow.example/logo.png",  # asset
        "https://ow.example/tag/investing",  # listing page
        "https://ow.example/pricing/",  # duplicate after normalization
        "https://ow.example/",
    ]
    assert prioritize(urls, "https://ow.example", limit=3) == [
        "https://ow.example/",
        "https://ow.example/pricing",
        "https://www.ow.example/features",
    ]


ARTICLE = """<html><head><title>OpenWealth – Portfolio analytics</title></head><body>
<nav><a href="/pricing">Pricing</a> <a href="https://x.example/">X</a> <a href="#top">Top</a></nav>
<main><h1>See your whole portfolio</h1>
<p>OpenWealth aggregates your brokerage accounts and shows allocation, fees and diversification
in one dashboard. It is built for self-directed retail investors who want clarity.</p>
<p>Connect accounts read-only, then explore exposure by sector, region and asset class.</p></main>
<footer>© 2026</footer></body></html>"""


def test_extract_text_and_links():
    out = extract_text(ARTICLE, "https://ow.example/")
    assert "aggregates your brokerage accounts" in out.text
    assert out.title  # trafilatura picks the <title> or the main H1
    links = extract_links(ARTICLE, "https://ow.example/")
    assert "https://ow.example/pricing" in links
    assert "https://x.example/" in links


def _next_page(payload_html: str, description="Guide to diversification") -> str:
    """A client-rendered Next.js page: empty DOM, content escaped inside __next_f pushes."""
    import json

    rsc = '5:["$","div",null,{"dangerouslySetInnerHTML":{"__html":' + json.dumps(payload_html) + "}}]\n"
    # Split across two pushes like Next.js does, and keep a raw newline inside the string.
    half = len(rsc) // 2
    parts = (rsc[:half], rsc[half:])
    pushes = "".join(f"<script>self.__next_f.push({json.dumps([1, part])})</script>" for part in parts)
    return (f'<html><head><title>Diversification | OW</title><meta name="description" content="{description}">'
            f'</head><body><div id="root"></div>{pushes}</body></html>')


def test_extracts_nextjs_embedded_html():
    body = "Spreading investments across assets lowers risk. " * 10
    article = f"<h2>What is diversification?</h2>\n<p>{body}</p>"
    out = extract_text(_next_page(article), "https://ow.example/blog/d")
    assert "Spreading investments across assets" in out.text
    assert out.description == "Guide to diversification"


def test_client_rendered_page_keeps_title_and_description():
    out = extract_text(_next_page("<span>x</span>"), "https://ow.example/")
    assert out.text == "" or len(out.text) < 50
    assert out.title and out.description == "Guide to diversification"


def test_extraction_has_no_cross_call_memory():
    """The same page extracted twice must give the same text (trafilatura's dedup cache is global)."""
    texts = [extract_text(ARTICLE, f"https://ow.example/{i}").text for i in range(6)]
    assert texts[0] and all(t == texts[0] for t in texts)
