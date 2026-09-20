"""LangSmith wrapping.

A real onboarding run died here: langsmith's wrap_anthropic assigns
`client.completions.create`, the anthropic 1.x SDK no longer has `completions`, and the
AttributeError surfaced as a failed run. Tracing is observability and must never be the
thing that breaks a pipeline.
"""

import anthropic
import pytest

from llm.tracing import trace_group, wrap_client


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


# --- Grouping a run's calls under one span -------------------------------------------------


# langsmith builds its run tree in memory regardless of whether the send succeeds, and the
# tree is what these tests assert on. config/settings/test.py points its endpoint at a dead
# address so nothing leaves the machine.


def test_trace_group_is_a_noop_when_tracing_is_off(settings):
    settings.LANGSMITH_TRACING = False
    with trace_group("reddit run #1") as span:
        assert span is None


def test_a_runs_llm_calls_become_children_of_one_span(settings):
    """Without a parent span every llm.complete() is its own root trace — which is what made
    LangSmith show a thread per call instead of a thread per agent run."""
    from langsmith import traceable as ls_traceable
    from langsmith.run_helpers import get_current_run_tree

    settings.LANGSMITH_TRACING = True
    seen = []

    @ls_traceable(run_type="chain")
    def one_call(n):
        tree = get_current_run_tree()
        seen.append((tree.parent_run_id, tree.trace_id))
        return n

    with trace_group("reddit run #7", metadata={"agent_run_id": 7}) as span:
        one_call(1)
        one_call(2)

    assert span is not None
    assert [c.name for c in span.child_runs] == ["one_call", "one_call"]
    assert all(parent_id == span.id for parent_id, _ in seen)
    assert {trace_id for _, trace_id in seen} == {span.trace_id}


def test_a_broken_span_does_not_stop_the_run(settings, monkeypatch, caplog):
    settings.LANGSMITH_TRACING = True

    def explode(*args, **kwargs):
        raise RuntimeError("langsmith unavailable")

    monkeypatch.setattr("langsmith.trace", explode)

    with caplog.at_level("WARNING"):
        with trace_group("reddit run #7") as span:
            assert span is None
    assert "continuing untraced" in caplog.text


def test_a_pipeline_exception_still_propagates_through_the_span(settings):
    """The guard covers opening the span, never the body — a pipeline error must surface."""
    settings.LANGSMITH_TRACING = True
    with pytest.raises(ValueError, match="pipeline blew up"):
        with trace_group("reddit run #7"):
            raise ValueError("pipeline blew up")
