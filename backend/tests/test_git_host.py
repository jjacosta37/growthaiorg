"""GitHubAppHost: token narrowing, the write guard, error mapping and installation checks, with
GitHub faked at the HTTP layer. FakeGitHost's own behaviour is covered by the publishing tests."""

import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from providers.git_host import GitHubAppHost, NeedsReconnect, NotFound, Unavailable, UnsafeBranch

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()


class GitHubStub:
    """Answers GitHub API calls from a routing table and records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.host}{request.url.path}"
        for pattern, answer in self.routes.items():
            if key == pattern:
                status, body = answer(request) if callable(answer) else answer
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": "Not Found"})


def host_with(routes) -> tuple[GitHubAppHost, GitHubStub]:
    stub = GitHubStub({
        "POST api.github.com/app/installations/7/access_tokens": (201, {"token": "inst-token"}),
        **routes,
    })
    client = httpx.Client(transport=httpx.MockTransport(stub))
    return GitHubAppHost("123", "luka-app", PEM, "cid", "csecret", client=client), stub


def token_requests(stub):
    return [json.loads(r.content) for r in stub.requests if r.url.path.endswith("/access_tokens")]


def test_the_app_jwt_is_signed_by_the_app_key_and_short_lived():
    host, stub = host_with({"GET api.github.com/repos/acme/site/branches/main":
                            (200, {"name": "main", "commit": {"sha": "abc"}, "protected": True})})
    host.get_branch(7, "acme/site", "main")
    auth = stub.requests[0].headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(auth, KEY.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "123"
    assert claims["exp"] - claims["iat"] <= 600


def test_tokens_are_narrowed_to_one_repo_and_read_only_for_reads():
    host, stub = host_with({"GET api.github.com/repos/acme/site/branches/main":
                            (200, {"name": "main", "commit": {"sha": "abc"}, "protected": False})})
    branch = host.get_branch(7, "acme/site", "main")
    assert branch.sha == "abc" and branch.protected is False
    [body] = token_requests(stub)
    assert body["repositories"] == ["site"]
    assert set(body["permissions"].values()) == {"read"}


def test_writes_ask_for_write_tokens_and_reuse_them():
    host, stub = host_with({
        "PUT api.github.com/repos/acme/site/contents/blog/a.md": (201, {}),
        "PATCH api.github.com/repos/acme/site/pulls/3": (200, {}),
    })
    host.put_file(7, "acme/site", "luka/1-a", "blog/a.md", "hello", "Add post")
    host.update_pr(7, "acme/site", 3, "T", "B")
    [body] = token_requests(stub)  # one write token served both calls
    assert body["permissions"]["contents"] == "write"
    put = next(r for r in stub.requests if r.method == "PUT")
    assert json.loads(put.content)["branch"] == "luka/1-a"


@pytest.mark.parametrize("branch", ["main", "master", "release/luka/x", "luka/"])
def test_writes_outside_lukas_branches_are_refused_before_any_request(branch):
    host, stub = host_with({})
    with pytest.raises(UnsafeBranch):
        host.put_file(7, "acme/site", branch, "blog/a.md", "x", "m")
    with pytest.raises(UnsafeBranch):
        host.ensure_branch(7, "acme/site", branch, "sha")
    with pytest.raises(UnsafeBranch):
        host.delete_file(7, "acme/site", branch, "blog/a.md", "sha", "m")
    with pytest.raises(UnsafeBranch):
        host.create_pr(7, "acme/site", branch, "main", "t", "b")
    assert stub.requests == []


@pytest.mark.parametrize("status,body,error", [
    (401, {"message": "Bad credentials"}, NeedsReconnect),
    (403, {"message": "Resource not accessible by integration"}, NeedsReconnect),
    (403, {"message": "API rate limit exceeded"}, Unavailable),
    (404, {"message": "Not Found"}, NotFound),
    (502, {"message": "bad gateway"}, Unavailable),
])
def test_http_failures_map_to_our_errors_without_githubs_text(status, body, error):
    host, _ = host_with({"GET api.github.com/repos/acme/site/branches/main": (status, body)})
    with pytest.raises(error) as caught:
        host.get_branch(7, "acme/site", "main")
    assert body["message"] not in caught.value.reason


def test_an_uninstalled_app_needs_reconnecting():
    host, _ = host_with({"POST api.github.com/app/installations/7/access_tokens": (404, {})})
    with pytest.raises(NeedsReconnect):
        host.list_repos(7)


def test_a_missing_file_has_no_sha():
    host, _ = host_with({})
    assert host.file_sha(7, "acme/site", "blog/new.md", "main") is None


def test_an_existing_file_reports_its_sha():
    host, stub = host_with({"GET api.github.com/repos/acme/site/contents/blog/a.md": (200, {"sha": "s1"})})
    assert host.file_sha(7, "acme/site", "blog/a.md", "main") == "s1"
    assert stub.requests[-1].url.params["ref"] == "main"


def test_an_existing_branch_is_not_recreated():
    host, stub = host_with({"GET api.github.com/repos/acme/site/git/ref/heads/luka/1-a": (200, {})})
    host.ensure_branch(7, "acme/site", "luka/1-a", "sha")
    assert not any(r.method == "POST" and r.url.path.endswith("/git/refs") for r in stub.requests)


def test_installation_is_verified_against_the_users_own_list():
    host, stub = host_with({
        "POST github.com/login/oauth/access_token": (200, {"access_token": "user-token"}),
        "GET api.github.com/user/installations": (200, {"installations": [{"id": 7, "account": {"login": "acme"}}]}),
    })
    installation = host.verify_installation("code", 7)
    assert installation.account == "acme"
    listing = next(r for r in stub.requests if r.url.path == "/user/installations")
    assert listing.headers["Authorization"] == "Bearer user-token"


def test_someone_elses_installation_is_refused():
    host, _ = host_with({
        "POST github.com/login/oauth/access_token": (200, {"access_token": "user-token"}),
        "GET api.github.com/user/installations": (200, {"installations": [{"id": 8, "account": {"login": "x"}}]}),
    })
    with pytest.raises(NotFound):
        host.verify_installation("code", 7)


def test_a_rejected_oauth_code_is_refused():
    host, _ = host_with({"POST github.com/login/oauth/access_token": (200, {"error": "bad_verification_code"})})
    with pytest.raises(NotFound):
        host.verify_installation("code", 7)


def test_install_url_carries_the_state():
    host, _ = host_with({})
    assert host.install_url("s.t") == "https://github.com/apps/luka-app/installations/new?state=s.t"


def test_a_network_failure_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("down")

    host = GitHubAppHost("123", "luka-app", PEM, "cid", "csecret",
                         client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(Unavailable):
        host.list_repos(7)
