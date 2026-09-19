import json

import pytest

from llm import batch
from llm.models import LLMBatch, LLMCall
from tests.conftest import write_prompt
from tests.fakes import message, usage

pytestmark = pytest.mark.django_db


@pytest.fixture
def scoring_prompt(prompts_tmp):
    write_prompt(prompts_tmp, "t.score", "v1", "model_tier: fast\nmax_tokens: 300\nschema: SmokeResult",
                 "Score.", "Item {{ n }}")


def test_submit_poll_collect(scoring_prompt, fake_anthropic):
    fake = fake_anthropic()
    answers = {
        "post-1": message(json.dumps({"ok": True, "echo": "one"}), usage_=usage(1_000_000, 0)),
        "post-2": message("not json"),
        "post-3": ("errored", "overloaded_error"),
        "post-4": ("expired", None),
        "post-5": message("", stop_reason="refusal"),
    }
    fake.messages.batches.answer = lambda cid, params: answers[cid]
    fake.messages.batches.ended = False

    b = batch.submit("t.score", [(cid, {"n": cid}) for cid in answers], meta={"k": "v"})

    reqs = fake.messages.batches.created[0]
    assert [r["custom_id"] for r in reqs] == list(answers)
    assert reqs[0]["params"]["messages"][0]["content"] == "Item post-1"
    assert reqs[0]["params"]["output_config"]["format"]["type"] == "json_schema"
    assert (b.status, b.request_count, b.prompt_version, b.meta) == ("submitted", 5, "v1", {"k": "v"})

    assert batch.is_done(b) is False
    fake.messages.batches.ended = True
    assert batch.is_done(b) is True
    b.refresh_from_db()
    assert b.status == "ended" and b.ended_at

    results = batch.collect(b)

    assert results["post-1"].ok and results["post-1"].parsed.echo == "one"
    assert not results["post-2"].ok and "schema" in results["post-2"].error
    assert "errored" in results["post-3"].error and "overloaded" in results["post-3"].error
    assert "expired" in results["post-4"].error
    assert not results["post-5"].ok and "refused" in results["post-5"].error

    calls = {c.custom_id: c for c in LLMCall.objects.filter(batch=b)}
    assert len(calls) == 5 and all(c.is_batch for c in calls.values())
    assert calls["post-1"].cost_usd == pytest.approx(0.5)  # $1/M input on Haiku, halved
    assert [calls[k].status for k in answers] == ["ok", "invalid_output", "error", "error", "refused"]
    b.refresh_from_db()
    assert (b.status, b.succeeded_count, b.errored_count) == ("collected", 1, 4)


def test_submit_rejects_empty(scoring_prompt, fake_anthropic):
    fake_anthropic()
    with pytest.raises(ValueError):
        batch.submit("t.score", [])
    assert not LLMBatch.objects.exists()
