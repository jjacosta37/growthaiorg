"""The guarded HTTP client: tenant-directed fetches only ever connect to public addresses.

These guard the crawler SSRF fix (docs/security-patterns.md §6). Nothing here opens a real
connection: resolvers are fakes, and the one path that reaches the socket layer is stopped
before it connects.
"""

import httpcore
import httpx
import pytest

from providers.crawl.http import (
    BlockedAddress,
    GuardedBackend,
    check_public_url,
    guarded_client,
    is_public_ip,
    resolve_public,
)


def dns(*addresses):
    def resolve(host, port, **kwargs):
        return [(2, 1, 6, "", (a, port)) for a in addresses]
    return resolve


@pytest.mark.parametrize("ip", [
    "10.0.0.5", "172.16.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:192.168.1.1", "not-an-ip",
])
def test_non_public_addresses_are_rejected(ip):
    assert not is_public_ip(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert is_public_ip(ip)


def test_a_name_that_resolves_privately_is_blocked():
    with pytest.raises(BlockedAddress):
        resolve_public("intranet.example", 80, dns("192.168.1.10"))


def test_one_private_answer_among_public_ones_blocks_the_host():
    with pytest.raises(BlockedAddress):
        resolve_public("rebind.example", 80, dns("93.184.216.34", "10.0.0.5"))


def test_a_name_that_does_not_resolve_is_blocked_with_the_dns_error_as_cause():
    def nxdomain(host, port, **kwargs):
        raise OSError("Name or service not known")

    with pytest.raises(BlockedAddress) as exc_info:
        resolve_public("typo.example", 80, nxdomain)
    assert isinstance(exc_info.value.__cause__, OSError)


def test_ip_literals_are_checked_without_dns():
    def no_dns(*args, **kwargs):
        raise AssertionError("an IP literal must not be resolved")

    assert resolve_public("93.184.216.34", 80, no_dns) == "93.184.216.34"
    with pytest.raises(BlockedAddress):
        resolve_public("[::1]", 80, no_dns)


def test_backend_connects_to_the_checked_address_not_the_hostname(monkeypatch):
    connected = []
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp",
                        lambda self, host, port, **kwargs: connected.append((host, port)))

    GuardedBackend(dns("93.184.216.34")).connect_tcp("example.com", 443)

    assert connected == [("93.184.216.34", 443)]


def test_backend_never_connects_to_a_private_address(monkeypatch):
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp",
                        lambda *args, **kwargs: pytest.fail("connected to a blocked host"))

    with pytest.raises(BlockedAddress):
        GuardedBackend(dns("127.0.0.1")).connect_tcp("localhost.example", 8000)


def test_guarded_client_blocks_through_the_real_transport():
    """The whole stack: httpx → transport → our pool → GuardedBackend. Breaks if an httpx
    upgrade stops the pool replacement in `guarded_client` from taking effect."""
    client = guarded_client(resolve=dns("10.0.0.5"))

    with pytest.raises(httpx.ConnectError) as exc_info:
        client.get("http://router.example/admin")
    assert isinstance(exc_info.value.__cause__, BlockedAddress)


def test_guarded_client_does_not_follow_redirects_or_use_env_proxies():
    client = guarded_client()
    assert client.follow_redirects is False
    assert client.trust_env is False


@pytest.mark.parametrize("url", [
    "http://127.0.0.1", "http://[::1]:8000/", "http://192.168.1.1/admin", "http://169.254.169.254/latest",
    "http://localhost:8000", "http://printer.local", "http://nas.home.arpa", "http://svc.internal",
])
def test_check_public_url_rejects_local_hosts(url):
    with pytest.raises(ValueError):
        check_public_url(url)


@pytest.mark.parametrize("url", ["https://example.com", "http://93.184.216.34/", "https://www.example.co.uk/x"])
def test_check_public_url_accepts_public_sites(url):
    check_public_url(url)
