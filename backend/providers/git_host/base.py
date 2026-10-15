"""Git hosting interface. Publishing depends on this, not on GitHub, so tests and local dev run
against an in-memory host and another host could be added behind the same calls.

Every write names a branch, and a host refuses any branch outside `BRANCH_PREFIX`. That is the
code-level half of "Luka never pushes to the base branch"; branch protection on the customer's
repository is the half GitHub enforces (docs/security-patterns.md §7).
"""

from dataclasses import dataclass, field
from typing import Protocol

BRANCH_PREFIX = "luka/"


class GitHostError(Exception):
    """A host call failed. `reason` is a short message written by Luka, safe to show the user;
    the host's own response text never reaches it."""

    reason = "GitHub couldn't complete the request"

    def __init__(self, reason: str = ""):
        super().__init__(reason or self.reason)
        if reason:
            self.reason = reason


class NeedsReconnect(GitHostError):
    """The installation is gone, suspended or lacks a permission: the user must reconnect."""

    reason = "Luka no longer has access to this repository. Reconnect GitHub in Settings."


class NotFound(GitHostError):
    """The repository, branch or file doesn't exist (or isn't visible to the installation)."""

    reason = "The repository or branch no longer exists"


class Unavailable(GitHostError):
    """The host timed out, errored or rate-limited us. Worth retrying later."""

    reason = "GitHub didn't respond. Try again in a few minutes."


class UnsafeBranch(ValueError):
    """A write was aimed at a branch outside BRANCH_PREFIX. A bug, never a user error."""


def check_writable(branch: str) -> None:
    """Refuse a write to any branch Luka didn't create.

    Raises:
        UnsafeBranch: `branch` doesn't start with BRANCH_PREFIX.
    """
    if not branch.startswith(BRANCH_PREFIX) or len(branch) <= len(BRANCH_PREFIX):
        raise UnsafeBranch(f"refusing to write to branch {branch!r}")


@dataclass
class Installation:
    """An installation the connecting user can access, as verified with the host.

    `repos` are the repositories in it that this user can push to themselves. The host lists
    an installation for anyone who can merely read one of its repositories, and Luka then acts
    with the installation's own access, so this set is what a project may be pointed at.
    """

    id: int
    account: str
    repos: list[str] = field(default_factory=list)


@dataclass
class Repo:
    full_name: str  # "owner/name"
    default_branch: str
    private: bool = True


@dataclass
class Branch:
    name: str
    sha: str
    protected: bool = False


@dataclass
class PullRequest:
    number: int
    url: str


class GitHost(Protocol):
    """What publishing needs from a git host. Every call can raise a GitHostError subclass."""

    name: str

    def install_url(self, state: str) -> str:
        """Where to send the browser to install the app; the host returns `state` unchanged."""
        ...

    def verify_installation(self, code: str, installation_id: int) -> Installation:
        """Check, as the user who just authorised, that `installation_id` is one of theirs, and
        which of its repositories they can push to.

        Raises:
            NotFound: The installation isn't among the user's.
        """
        ...

    def list_repos(self, installation_id: int) -> list[Repo]: ...

    def get_branch(self, installation_id: int, repo: str, branch: str) -> Branch: ...

    def file_sha(self, installation_id: int, repo: str, path: str, ref: str) -> str | None:
        """The blob sha of `path` on `ref`, or None if there's no file there."""
        ...

    def ensure_branch(self, installation_id: int, repo: str, branch: str, from_sha: str) -> None:
        """Create `branch` at `from_sha` unless it already exists."""
        ...

    def put_file(self, installation_id: int, repo: str, branch: str, path: str, text: str, message: str,
                 sha: str | None = None) -> None:
        """Create `path` on `branch`, or replace it when `sha` (its current blob sha) is given."""
        ...

    def delete_file(self, installation_id: int, repo: str, branch: str, path: str, sha: str, message: str) -> None: ...

    def find_open_pr(self, installation_id: int, repo: str, head: str) -> PullRequest | None: ...

    def create_pr(self, installation_id: int, repo: str, head: str, base: str, title: str,
                  body: str) -> PullRequest: ...

    def update_pr(self, installation_id: int, repo: str, number: int, title: str, body: str) -> None: ...
