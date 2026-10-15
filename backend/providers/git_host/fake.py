"""In-memory GitHost for tests and for local dev without a GitHub App (GIT_HOST=fake)."""

from dataclasses import dataclass, field

from .base import Branch, GitHostError, Installation, NotFound, PullRequest, Repo, check_writable


@dataclass
class FakeRepo:
    """One repository: branches as {name: {path: text}}, plus the PRs opened against it."""

    default_branch: str = "main"
    branches: dict[str, dict[str, str]] = field(default_factory=lambda: {"main": {}})
    protected: set[str] = field(default_factory=lambda: {"main"})
    prs: list[dict] = field(default_factory=list)


class FakeGitHost:
    """GitHost with no network. Records every write in `writes` so tests can assert what was
    touched, and raises `fail` (a GitHostError) from every call when it is set."""

    name = "fake"

    def __init__(self, repos: dict[str, FakeRepo] | None = None, *, installations: dict[int, str] | None = None):
        self.repos = repos if repos is not None else {"acme/site": FakeRepo()}
        self.installations = installations if installations is not None else {1: "acme"}
        self.writes: list[tuple] = []
        self.fail: GitHostError | None = None

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def _repo(self, repo: str) -> FakeRepo:
        self._check()
        if repo not in self.repos:
            raise NotFound()
        return self.repos[repo]

    def install_url(self, state: str) -> str:
        """A local stand-in for the install page."""
        return f"https://github.invalid/apps/luka/installations/new?state={state}"

    def verify_installation(self, code: str, installation_id: int) -> Installation:
        """Accepts any code; the installation must be one of `installations`."""
        self._check()
        if installation_id not in self.installations:
            raise NotFound("That GitHub installation isn't one of yours")
        return Installation(id=installation_id, account=self.installations[installation_id])

    def list_repos(self, installation_id: int) -> list[Repo]:
        """Every repository in the fake."""
        self._check()
        return [Repo(full_name=name, default_branch=r.default_branch) for name, r in self.repos.items()]

    def get_branch(self, installation_id: int, repo: str, branch: str) -> Branch:
        """The branch, with a sha derived from its files."""
        r = self._repo(repo)
        if branch not in r.branches:
            raise NotFound()
        return Branch(name=branch, sha=f"sha-{branch}-{len(r.branches[branch])}", protected=branch in r.protected)

    def file_sha(self, installation_id: int, repo: str, path: str, ref: str) -> str | None:
        """A stand-in sha when the file exists on `ref`."""
        r = self._repo(repo)
        if ref not in r.branches:
            raise NotFound()
        return f"blob-{path}" if path in r.branches[ref] else None

    def ensure_branch(self, installation_id: int, repo: str, branch: str, from_sha: str) -> None:
        """Copy the default branch's files into a new branch."""
        check_writable(branch)
        r = self._repo(repo)
        if branch not in r.branches:
            source = next((b for b in r.branches if from_sha.startswith(f"sha-{b}-")), r.default_branch)
            r.branches[branch] = dict(r.branches[source])
            self.writes.append(("ensure_branch", repo, branch))

    def put_file(self, installation_id: int, repo: str, branch: str, path: str, text: str, message: str,
                 sha: str | None = None) -> None:
        """Write the file on the branch."""
        check_writable(branch)
        r = self._repo(repo)
        if branch not in r.branches:
            raise NotFound()
        if (path in r.branches[branch]) != bool(sha):
            raise GitHostError("sha mismatch")
        r.branches[branch][path] = text
        self.writes.append(("put_file", repo, branch, path))

    def delete_file(self, installation_id: int, repo: str, branch: str, path: str, sha: str, message: str) -> None:
        """Remove the file from the branch."""
        check_writable(branch)
        r = self._repo(repo)
        r.branches[branch].pop(path, None)
        self.writes.append(("delete_file", repo, branch, path))

    def find_open_pr(self, installation_id: int, repo: str, head: str) -> PullRequest | None:
        """The open PR from `head`, if any."""
        r = self._repo(repo)
        pr = next((p for p in r.prs if p["head"] == head and p["state"] == "open"), None)
        return PullRequest(number=pr["number"], url=pr["url"]) if pr else None

    def create_pr(self, installation_id: int, repo: str, head: str, base: str, title: str,
                  body: str) -> PullRequest:
        """Record an open PR."""
        check_writable(head)
        r = self._repo(repo)
        number = len(r.prs) + 1
        url = f"https://github.com/{repo}/pull/{number}"
        r.prs.append({"number": number, "url": url, "head": head, "base": base, "title": title, "body": body,
                      "state": "open"})
        self.writes.append(("create_pr", repo, head, base))
        return PullRequest(number=number, url=url)

    def update_pr(self, installation_id: int, repo: str, number: int, title: str, body: str) -> None:
        """Replace the PR's title and body."""
        r = self._repo(repo)
        pr = next(p for p in r.prs if p["number"] == number)
        pr.update(title=title, body=body)
        self.writes.append(("update_pr", repo, number))
