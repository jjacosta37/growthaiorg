"""GitHost backed by a GitHub App.

Luka authenticates as the app with a short-lived JWT signed by the app's private key, and
exchanges it for an installation token for each step. Tokens are narrowed to the one
repository and the permissions the step needs (read-only checks get read-only tokens), live
for at most an hour, and are never stored or logged.

All hosts are fixed (api.github.com, github.com). Requests go through the guarded client, so
the module that builds HTTP clients stays the only one (docs/security-patterns.md §6).
"""

import base64
import logging
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import jwt

from llm.tracing import trace_tool
from providers.crawl.http import guarded_client

from .base import (
    Branch,
    GitHostError,
    Installation,
    NeedsReconnect,
    NotFound,
    PullRequest,
    Repo,
    Unavailable,
    check_writable,
)

log = logging.getLogger(__name__)

API = "https://api.github.com"
WEB = "https://github.com"
READ = {"contents": "read", "metadata": "read", "pull_requests": "read"}
WRITE = {"contents": "write", "metadata": "read", "pull_requests": "write"}
MAX_PAGES = 10  # 1,000 repositories or installations is far beyond any one account's blog


def _owner_name(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    return owner, name


class GitHubAppHost:
    """GitHost for one GitHub App (one per Luka deployment)."""

    name = "github"

    def __init__(self, app_id: str, slug: str, private_key: str, client_id: str, client_secret: str, *,
                 client: httpx.Client | None = None):
        self.app_id = app_id
        self.slug = slug
        self.private_key = private_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = client or guarded_client()
        self._tokens: dict[tuple, tuple[str, float]] = {}

    # --- authentication -------------------------------------------------------------------

    def _app_jwt(self) -> str:
        now = int(time.time())
        # iat is backdated to allow for clock drift; GitHub caps exp at 10 minutes.
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.private_key,
                          algorithm="RS256")

    def _token(self, installation_id: int, repo: str | None, permissions: dict[str, str]) -> str:
        """An installation token for one repository (or all, for listing) with `permissions`."""
        key = (installation_id, repo, tuple(sorted(permissions.items())))
        cached = self._tokens.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        body: dict[str, Any] = {"permissions": permissions}
        if repo:
            body["repositories"] = [_owner_name(repo)[1]]
        data = self._request("POST", f"/app/installations/{installation_id}/access_tokens", bearer=self._app_jwt(),
                             json=body, missing=NeedsReconnect)
        # Tokens last an hour; reuse one for 50 minutes at most.
        self._tokens[key] = (data["token"], time.monotonic() + 50 * 60)
        return data["token"]

    # --- HTTP -----------------------------------------------------------------------------

    def _request(self, method: str, path: str, *, bearer: str | None, json: dict | None = None,
                 params: dict | None = None, missing: type[GitHostError] = NotFound,
                 base: str = API) -> Any:
        """One API call. Maps failures to GitHostError subclasses; the response body never
        reaches the message, because it can echo request content."""
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if base == WEB:  # the OAuth endpoint answers JSON only when asked for plain JSON
            headers["Accept"] = "application/json"
        try:
            response = self.http.request(method, f"{base}{path}", headers=headers, json=json, params=params)
        except httpx.HTTPError as exc:
            log.warning("github %s %s failed: %s", method, path.split("?")[0], type(exc).__name__, exc_info=True)
            raise Unavailable() from exc
        status = response.status_code
        if status < 300:
            return response.json() if response.content else None
        log.warning("github %s %s returned HTTP %s", method, path.split("?")[0], status)
        if status == 401:
            raise NeedsReconnect()
        if status == 403:
            if response.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in response.text.lower():
                raise Unavailable()
            raise NeedsReconnect()
        if status == 404:
            raise missing()
        if status == 429 or status >= 500:
            raise Unavailable()
        raise GitHostError()

    def _call(self, op: str, repo: str, fn, **inputs):
        """Run one operation inside a tool span with the facts that explain it."""
        started = time.monotonic()
        with trace_tool(f"github.{op}", inputs={"repo": repo, **inputs}) as outputs:
            try:
                result = fn()
            except GitHostError as exc:
                outputs.update(status="error", error=type(exc).__name__,
                               duration_ms=int((time.monotonic() - started) * 1000))
                raise
            outputs.update(status="ok", duration_ms=int((time.monotonic() - started) * 1000))
            return result

    # --- connecting -----------------------------------------------------------------------

    def install_url(self, state: str) -> str:
        """The app's install page; GitHub sends the browser back to the app's setup URL."""
        return f"{WEB}/apps/{quote(self.slug)}/installations/new?{urlencode({'state': state})}"

    def verify_installation(self, code: str, installation_id: int) -> Installation:
        """Exchange the OAuth code for a user token and look for the installation among the
        user's own. The user token is used for this check only and then dropped."""

        def run() -> Installation:
            data = self._request("POST", "/login/oauth/access_token", bearer=None, base=WEB, json={
                "client_id": self.client_id, "client_secret": self.client_secret, "code": code})
            user_token = (data or {}).get("access_token")
            if not user_token:
                raise NotFound("GitHub didn't confirm the authorisation. Try connecting again.")
            for page in range(1, MAX_PAGES + 1):
                listing = self._request("GET", "/user/installations", bearer=user_token,
                                        params={"per_page": 100, "page": page})
                for item in listing.get("installations", []):
                    if item.get("id") == installation_id:
                        return Installation(id=installation_id, account=item.get("account", {}).get("login", ""),
                                            repos=self._pushable(user_token, installation_id))
                if len(listing.get("installations", [])) < 100:
                    break
            raise NotFound("That GitHub installation isn't one of yours")

        return self._call("verify_installation", "", run)

    def _pushable(self, user_token: str, installation_id: int) -> list[str]:
        """Repositories in the installation that the user can push to (or administers)."""
        repos: list[str] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._request("GET", f"/user/installations/{installation_id}/repositories", bearer=user_token,
                                 params={"per_page": 100, "page": page})
            items = data.get("repositories", [])
            repos += [r["full_name"] for r in items
                      if (r.get("permissions") or {}).get("push") or (r.get("permissions") or {}).get("admin")]
            if len(items) < 100:
                break
        return repos

    # --- reading --------------------------------------------------------------------------

    def list_repos(self, installation_id: int) -> list[Repo]:
        """The repositories the user granted the installation."""

        def run() -> list[Repo]:
            token = self._token(installation_id, None, {"metadata": "read"})
            repos: list[Repo] = []
            for page in range(1, MAX_PAGES + 1):
                data = self._request("GET", "/installation/repositories", bearer=token,
                                     params={"per_page": 100, "page": page})
                items = data.get("repositories", [])
                repos += [Repo(full_name=r["full_name"], default_branch=r.get("default_branch") or "main",
                               private=bool(r.get("private"))) for r in items]
                if len(items) < 100:
                    break
            return repos

        return self._call("list_repos", "", run)

    def get_branch(self, installation_id: int, repo: str, branch: str) -> Branch:
        """A branch's head commit and whether GitHub protects it."""

        def run() -> Branch:
            token = self._token(installation_id, repo, READ)
            data = self._request("GET", f"/repos/{repo}/branches/{quote(branch, safe='')}", bearer=token)
            return Branch(name=data["name"], sha=data["commit"]["sha"], protected=bool(data.get("protected")))

        return self._call("get_branch", repo, run, branch=branch)

    def file_sha(self, installation_id: int, repo: str, path: str, ref: str) -> str | None:
        """The blob sha of `path` on `ref`, or None if no file is there."""

        def run() -> str | None:
            token = self._token(installation_id, repo, READ)
            try:
                data = self._request("GET", f"/repos/{repo}/contents/{quote(path)}", bearer=token,
                                     params={"ref": ref})
            except NotFound:
                return None
            return data.get("sha") if isinstance(data, dict) else "directory"

        return self._call("file_sha", repo, run, ref=ref)

    def find_open_pr(self, installation_id: int, repo: str, head: str) -> PullRequest | None:
        """The open PR from `head`, if one exists (so a retry never opens a second)."""

        def run() -> PullRequest | None:
            token = self._token(installation_id, repo, READ)
            owner = _owner_name(repo)[0]
            data = self._request("GET", f"/repos/{repo}/pulls", bearer=token,
                                 params={"head": f"{owner}:{head}", "state": "open"})
            return PullRequest(number=data[0]["number"], url=data[0]["html_url"]) if data else None

        return self._call("find_open_pr", repo, run, head=head)

    # --- writing (luka/ branches only) ----------------------------------------------------

    def ensure_branch(self, installation_id: int, repo: str, branch: str, from_sha: str) -> None:
        """Create `branch` at `from_sha`, or leave it if it exists."""
        check_writable(branch)

        def run() -> None:
            token = self._token(installation_id, repo, WRITE)
            try:
                self._request("GET", f"/repos/{repo}/git/ref/heads/{quote(branch)}", bearer=token)
                return
            except NotFound:
                pass
            self._request("POST", f"/repos/{repo}/git/refs", bearer=token,
                          json={"ref": f"refs/heads/{branch}", "sha": from_sha})

        self._call("ensure_branch", repo, run, branch=branch)

    def put_file(self, installation_id: int, repo: str, branch: str, path: str, text: str, message: str,
                 sha: str | None = None) -> None:
        """Commit `text` to `path` on `branch` (a replace when `sha` is given)."""
        check_writable(branch)

        def run() -> None:
            token = self._token(installation_id, repo, WRITE)
            body = {"message": message, "branch": branch,
                    "content": base64.b64encode(text.encode()).decode()}
            if sha:
                body["sha"] = sha
            self._request("PUT", f"/repos/{repo}/contents/{quote(path)}", bearer=token, json=body)

        self._call("put_file", repo, run, branch=branch)

    def delete_file(self, installation_id: int, repo: str, branch: str, path: str, sha: str, message: str) -> None:
        """Remove `path` from `branch` (used when a slug change renames the post)."""
        check_writable(branch)

        def run() -> None:
            token = self._token(installation_id, repo, WRITE)
            self._request("DELETE", f"/repos/{repo}/contents/{quote(path)}", bearer=token,
                          json={"message": message, "branch": branch, "sha": sha})

        self._call("delete_file", repo, run, branch=branch)

    def create_pr(self, installation_id: int, repo: str, head: str, base: str, title: str,
                  body: str) -> PullRequest:
        """Open a PR from Luka's branch into the base branch. Luka never merges it."""
        check_writable(head)

        def run() -> PullRequest:
            token = self._token(installation_id, repo, WRITE)
            data = self._request("POST", f"/repos/{repo}/pulls", bearer=token,
                                 json={"head": head, "base": base, "title": title, "body": body})
            return PullRequest(number=data["number"], url=data["html_url"])

        return self._call("create_pr", repo, run, head=head, base=base)

    def update_pr(self, installation_id: int, repo: str, number: int, title: str, body: str) -> None:
        """Refresh the PR's title and description."""

        def run() -> None:
            token = self._token(installation_id, repo, WRITE)
            self._request("PATCH", f"/repos/{repo}/pulls/{number}", bearer=token, json={"title": title, "body": body})

        self._call("update_pr", repo, run, number=number)
