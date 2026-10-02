"""The one HTTP client for URLs a tenant or a crawled page chooses.

Luka runs on the operator's home network, so a fetch that can be pointed at a private
address reaches the router, other devices and services on the host itself. Every TCP
connection this client opens resolves the host, refuses any non-public address, and then
connects to the exact address it checked. Checking at connect time covers every request
(robots.txt, sitemaps, pages, each redirect hop) and leaves no gap for DNS rebinding
between the check and the connection. TLS still uses the hostname for SNI and certificate
checks, because httpcore wraps TLS around the stream this backend returns.

See docs/security-patterns.md §6.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

import httpcore
import httpx

USER_AGENT = "LukaBot/0.1 (internal content assistant)"
TIMEOUT_SECONDS = 15.0

# getaddrinfo's shape: (host, port, family, type, ...) -> [(family, type, proto, canonname, sockaddr)]
Resolver = Callable[..., list[tuple]]

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa", ".localhost")


class BlockedAddress(httpcore.ConnectError):
    """A host resolved to an address the crawler must not connect to.

    Subclasses httpcore's ConnectError so httpx maps it to `httpx.ConnectError`; the
    original stays reachable as that exception's `__cause__`.
    """

    def __init__(self, host: str):
        super().__init__(f"{host} does not resolve to a public address")
        self.host = host


def is_public_ip(value: str) -> bool:
    """Whether an IP address is on the public internet.

    Rejects loopback, private, link-local (including cloud metadata), CGNAT, multicast,
    reserved and unspecified addresses, and the IPv4 addresses hidden inside IPv4-mapped
    IPv6 ones.
    """
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 4 and ip in _CGNAT:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def resolve_public(host: str, port: int, resolve: Resolver = socket.getaddrinfo) -> str:
    """Resolve `host` and return an address to connect to, if every address is public.

    One non-public answer blocks the host: an attacker who controls DNS can return a mix,
    and the connection would otherwise take whichever came first.

    Raises:
        BlockedAddress: the host is an IP literal or name that isn't public, or doesn't resolve.
    """
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        literal = True
    except ValueError:
        literal = False
    if literal:
        if not is_public_ip(host):
            raise BlockedAddress(host)
        return host
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise BlockedAddress(host) from exc
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise BlockedAddress(host)
    return addresses[0]


class GuardedBackend(httpcore.SyncBackend):
    """httpcore network backend that only opens connections to public addresses."""

    def __init__(self, resolve: Resolver = socket.getaddrinfo):
        self.resolve = resolve

    def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                    socket_options: Iterable | None = None) -> httpcore.NetworkStream:
        """Connect to the checked address of `host`, never to whatever a second lookup returns.

        Raises:
            BlockedAddress: `host` isn't public.
        """
        address = resolve_public(host, port, self.resolve)
        return super().connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                   socket_options=socket_options)

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Iterable | None = None) -> httpcore.NetworkStream:
        """Unix sockets are local by definition."""
        raise BlockedAddress(path)


def guarded_client(resolve: Resolver = socket.getaddrinfo) -> httpx.Client:
    """An httpx client for tenant-directed URLs: public addresses only, no automatic redirects.

    Redirects are left to the caller so it can apply its own same-site rule to each hop.
    `trust_env=False` stops proxy environment variables from rerouting the requests.
    httpx doesn't expose the network backend, so the transport's pool is replaced with one
    built on GuardedBackend; `tests/test_crawl_http.py` fails if an httpx upgrade breaks that.
    """
    limits = httpx.Limits()
    transport = httpx.HTTPTransport(trust_env=False)
    transport._pool = httpcore.ConnectionPool(
        ssl_context=httpx.create_ssl_context(trust_env=False),
        max_connections=limits.max_connections,
        max_keepalive_connections=limits.max_keepalive_connections,
        keepalive_expiry=limits.keepalive_expiry,
        network_backend=GuardedBackend(resolve),
    )
    return httpx.Client(transport=transport, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS,
                        follow_redirects=False, trust_env=False)


def check_public_url(url: str) -> None:
    """Reject a URL whose host is plainly local, without a DNS lookup.

    Used by serializers to give a clear 400 early. The real gate is GuardedBackend, which
    also catches public names that resolve to private addresses.

    Raises:
        ValueError: the host is a non-public IP literal or a local name.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("Enter a full website address, like https://example.com.")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if (literal and not is_public_ip(host)) or host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise ValueError("Enter a public website address. Local and private network addresses can't be crawled.")
