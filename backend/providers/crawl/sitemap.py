from dataclasses import dataclass, field

from lxml import etree

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)


@dataclass
class SitemapDoc:
    page_urls: list[str] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_sitemap(xml: bytes) -> SitemapDoc:
    """Parse a <urlset> or <sitemapindex>. Namespace-agnostic; tolerant of junk."""
    doc = SitemapDoc()
    try:
        root = etree.fromstring(xml, parser=_PARSER)
    except etree.XMLSyntaxError:
        return doc
    if root is None:
        return doc
    kind = _local(root.tag)
    for entry in root:
        loc = next((c.text for c in entry if _local(c.tag) == "loc" and c.text), None)
        if not loc:
            continue
        if kind == "sitemapindex":
            doc.child_sitemaps.append(loc.strip())
        elif kind == "urlset":
            doc.page_urls.append(loc.strip())
    return doc


def sitemaps_from_robots(robots_txt: str) -> list[str]:
    out = []
    for line in robots_txt.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            out.append(value.strip())
    return out
