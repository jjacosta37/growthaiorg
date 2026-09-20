"""LangSmith wrapping.

A real onboarding run died here: langsmith's wrap_anthropic assigns
`client.completions.create`, the anthropic 1.x SDK no longer has `completions`, and the
AttributeError surfaced as a failed run. Tracing is observability and must never be the
thing that breaks a pipeline.
"""

import anthropic
import pytest

from llm.tracing import wrap_client


def test_wrapping_is_skipped_when_tracing_is_off(settings):
    settings.LANGSMITH_TRACING = False
    client = anthropic.Anthropic(api_key="x")
    assert wrap_client(client) is client


def test_a_modern_anthropic_client_wraps_despite_having_no_completions(settings):
    """anthropic 1.x dropped the legacy Text Completions API."""
    settings.LANGSMITH_TRACING = True
    client = anthropic.Anthropic(api_key="x")
    assert not hasattr(anthropic.Anthropic(api_key="x"), "completions")

    original_create = client.messages.create
    wrapped = wrap_client(client)

    # The call we actually make is traced...
    assert wrapped.messages.create is not original_create
    # ...and the shim absorbed the assignment langsmith makes blindly.
    assert hasattr(wrapped, "completions")


def test_a_broken_wrapper_degrades_to_an_untraced_client(settings, monkeypatch, caplog):
    """Whatever goes wrong in langsmith, the run carries on."""
    settings.LANGSMITH_TRACING = True

    def explode(_client):
        raise RuntimeError("langsmith changed again")

    monkeypatch.setattr("langsmith.wrappers.wrap_anthropic", explode)

    client = anthropic.Anthropic(api_key="x")
    with caplog.at_level("WARNING"):
        assert wrap_client(client) is client
    assert "continuing untraced" in caplog.text


@pytest.mark.parametrize("missing", [True, False])
def test_the_shim_never_replaces_a_real_completions_attribute(settings, missing):
    settings.LANGSMITH_TRACING = True
    client = anthropic.Anthropic(api_key="x")

    sentinel = object()
    if not missing:
        client.completions = sentinel

    wrap_client(client)

    if missing:
        assert client.completions is not sentinel  # the shim filled the gap
    else:
        assert client.completions is sentinel  # a real one is left alone
