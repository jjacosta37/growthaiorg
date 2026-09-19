"""Assembles the sidebar status payload. Agent apps register contributors as they land."""

from collections.abc import Callable

_contributors: list[Callable] = []


def register_status_contributor(fn: Callable) -> Callable:
    """fn(project) -> dict merged into the status payload."""
    _contributors.append(fn)
    return fn


def build_status(project) -> dict:
    payload: dict = {"active": [], "message": None}
    for fn in _contributors:
        payload.update(fn(project))
    return payload
