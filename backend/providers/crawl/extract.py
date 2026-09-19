import json
import re
from dataclasses import dataclass

import trafilatura
from lxml import html as lxml_html

from .urls import normalize

# Next.js (app router) ships page content inside inline `self.__next_f.push([1, "..."])` scripts.
# Client-rendered pages show almost no text in the DOM, but server-provided HTML fragments (blog
# posts, legal pages) are often embedded there as escaped strings.
_NEXT_PUSH = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
_JSON_STRING = re.compile(r'"((?:[^"\\]|\\.){200,})"')
_HTML_TAG = re.compile(r"<(p|h[1-6]|li|article|section|table)\b", re.I)


@dataclass
class Extracted:
    title: str
    text: str
    description: str = ""


def _meta(tree, *names: str) -> str:
    for name in names:
        for attr in ("name", "property"):
            vals = tree.xpath(f'//meta[@{attr}="{name}"]/@content')
            if vals and vals[0].strip():
                return vals[0].strip()
    return ""


def _next_flight_text(html: str) -> str:
    payload = []
    for chunk in _NEXT_PUSH.findall(html):
        try:
            arr = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            payload.append(arr[1])
    if not payload:
        return ""
    fragments = []
    for m in _JSON_STRING.finditer("".join(payload)):
        try:
            value = json.loads(f'"{m.group(1)}"', strict=False)  # RSC text keeps raw newlines
        except json.JSONDecodeError:
            continue
        if _HTML_TAG.search(value):
            fragments.append(value)
    if not fragments:
        return ""
    doc = f"<html><body><article>{''.join(fragments)}</article></body></html>"
    return (trafilatura.extract(doc, include_tables=True, favor_recall=True) or "").strip()


def extract_text(html: str, url: str) -> Extracted:
    """Main content as plain text (boilerplate removed), plus title and meta description."""
    # No deduplicate=True: trafilatura's dedup cache is process-wide, so in a long-lived worker it
    # silently drops text that appeared on earlier pages or in earlier crawls.
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True) or ""
    flight = _next_flight_text(html)
    if len(flight) > len(text):
        text = flight
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else "") or ""
    try:
        tree = lxml_html.fromstring(html)
        description = _meta(tree, "description", "og:description", "twitter:description")
    except (ValueError, lxml_html.etree.ParserError):
        description = ""
    return Extracted(title=title.strip(), text=text.strip(), description=description)


def extract_links(html: str, base_url: str) -> list[str]:
    try:
        tree = lxml_html.fromstring(html)
    except (ValueError, lxml_html.etree.ParserError):
        return []
    links = []
    for href in tree.xpath("//a/@href"):
        if url := normalize(href, base_url):
            links.append(url)
    return links
