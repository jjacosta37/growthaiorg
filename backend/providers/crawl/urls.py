from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".json", ".xml",
    ".zip", ".gz", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".txt", ".csv", ".rss", ".atom",
}
# Low-value listing pages that crowd out real content.
SKIP_PATH_PARTS = ("/tag/", "/tags/", "/category/", "/categories/", "/author/", "/page/", "/wp-json/", "/feed")


def host_key(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize(url: str, base: str | None = None) -> str | None:
    """Absolute http(s) URL without fragment, query tracking noise, or trailing slash. None if unusable."""
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((p.scheme, p.netloc.lower(), path, "", p.query, ""))


def same_site(url: str, root: str) -> bool:
    return host_key(urlparse(url).netloc) == host_key(urlparse(root).netloc)


def is_crawlable(url: str) -> bool:
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    return not any(part in path + "/" for part in SKIP_PATH_PARTS)


def prioritize(urls: list[str], root: str, limit: int) -> list[str]:
    """Same-site, crawlable, deduplicated; homepage first, then shallow pages (product, pricing,
    about) before deep ones (individual blog posts), capped at `limit`."""
    seen: set[str] = set()
    picked: list[str] = []
    for raw in urls:
        url = normalize(raw)
        if not url or url in seen or not same_site(url, root) or not is_crawlable(url):
            continue
        seen.add(url)
        picked.append(url)

    def key(u: str):
        path = urlparse(u).path
        depth = 0 if path == "/" else path.count("/")
        return (depth, len(path), u)

    return sorted(picked, key=key)[:limit]
