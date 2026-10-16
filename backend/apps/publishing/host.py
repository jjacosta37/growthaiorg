"""The configured git host. Publishing code calls `get_git_host()` and never builds one itself."""

from django.conf import settings

from providers.git_host import FakeGitHost, GitHost, GitHubAppHost

_fake: FakeGitHost | None = None


def github_configured() -> bool:
    """Whether this deployment can connect to GitHub at all (the app's settings are present)."""
    if settings.GIT_HOST == "fake":
        return True
    return all([settings.GITHUB_APP_ID, settings.GITHUB_APP_SLUG, settings.GITHUB_APP_PRIVATE_KEY,
                settings.GITHUB_APP_CLIENT_ID, settings.GITHUB_APP_CLIENT_SECRET])


def get_git_host() -> GitHost:
    """GitHub in production; one in-memory fake per process for local dev (GIT_HOST=fake).

    Raises:
        RuntimeError: GitHub is configured but the app's settings are missing.
    """
    global _fake
    if settings.GIT_HOST == "fake":
        if _fake is None:
            _fake = FakeGitHost()
        return _fake
    if not github_configured():
        raise RuntimeError("The GitHub App isn't configured (see README: GitHub pull requests)")
    return GitHubAppHost(settings.GITHUB_APP_ID, settings.GITHUB_APP_SLUG, settings.GITHUB_APP_PRIVATE_KEY,
                         settings.GITHUB_APP_CLIENT_ID, settings.GITHUB_APP_CLIENT_SECRET)
