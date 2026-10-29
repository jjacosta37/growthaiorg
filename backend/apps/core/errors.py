"""Error helpers: JSON-safe validation errors, and the one message a user may see for an exception.

Exception text is written for developers. It can carry provider responses, request ids, URLs,
file paths or a key's fingerprint, so it never reaches the client (docs/security-patterns.md §10).
What the UI shows instead comes from `public_message`: the generic sentence, unless the error is
about something the user can fix themselves. The exception itself goes to the log and Sentry,
which is where the detail is read.
"""

GENERIC_FAILURE = "Something went wrong on Luka's side. It has been reported."


class UserFacingError(Exception):
    """An error the user can fix themselves (their settings, their site), told to them plainly.

    Only for problems on the user's side. A failure under the hood (a provider, the model, the
    server's own setup, a timeout) is a plain exception, so the UI shows the generic sentence
    and says nothing about what broke.

    Args:
        message: The developer's message: what the log and Sentry show.
        public: What the UI shows. Defaults to `message`, for errors whose message is already
            written for the user and carries nothing from a provider or the environment.
    """

    def __init__(self, message: str, *, public: str | None = None):
        super().__init__(message)
        self.public = public or message


def public_message(exc: BaseException) -> str:
    """The text the UI may show for `exc`: a UserFacingError's `public` text, or the generic sentence.

    Never `str(exc)`: only errors about the user's own input say anything specific. Checked by
    class, not by attribute, so another library's exception can't opt in by having a `public`.
    """
    if isinstance(exc, UserFacingError) and exc.public:
        return exc.public
    return GENERIC_FAILURE


def validation_errors(exc) -> list[dict]:
    """Pydantic validation errors as JSON-safe dicts (the default includes raw exception objects)."""
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors(include_url=False, include_context=False)]
