from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import llm
from apps.core.models import Project
from llm.context import set_context_provider
from llm.models import LLMCall
from tests.conftest import write_prompt
from tests.fakes import message, text_block, usage

pytestmark = pytest.mark.django_db

SCORE_FM = "model_tier: fast\nmax_tokens: 300\nschema: SmokeResult"


@pytest.fixture
def score_prompt(prompts_tmp):
    write_prompt(prompts_tmp, "t.score", "v1", SCORE_FM, "Score things.", "Word: {{ word }}")
    return prompts_tmp


def test_structured_output_parsed_and_logged(score_prompt, fake_anthropic, settings):
    fake = fake_anthropic(message('{"ok": true, "echo": "helm"}', usage_=usage(5000, 50, cache_read=4000)))

    result = llm.complete("t.score", {"word": "helm"})

    assert result.parsed.ok is True and result.parsed.echo == "helm"
    call = LLMCall.objects.get()
    assert call.status == "ok"
    assert call.model == settings.LLM_MODELS["fast"]
    assert (call.prompt_version, call.cache_read_tokens, call.request_id) == ("v1", 4000, "req_test")
    assert call.cost_usd > 0

    params = fake.messages.calls[0]
    assert params["model"] == settings.LLM_MODELS["fast"]
    fmt = params["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "effort" not in params["output_config"]  # Haiku rejects effort; only sent when set
    assert params["messages"] == [{"role": "user", "content": "Word: helm"}]


def test_context_block_is_first_and_cached(score_prompt, fake_anthropic, project):
    set_context_provider(lambda project: [("Product Information", "Acme helps small teams track projects.")])
    try:
        fake = fake_anthropic(message('{"ok": true, "echo": "x"}'))
        result = llm.complete("t.score", {"word": "x"}, project=project)
    finally:
        set_context_provider(None)

    assert result.call.project == project
    system = fake.messages.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "# Content rules" in system[0]["text"] and "`fabrication`" in system[0]["text"]  # general pack
    assert '<document title="Product Information">' in system[0]["text"]
    assert system[1] == {"type": "text", "text": "Score things."}


def test_invalid_output_retries_once_then_succeeds(score_prompt, fake_anthropic):
    fake = fake_anthropic(message('{"ok": "maybe"'), message('{"ok": false, "echo": "y"}'))
    result = llm.complete("t.score", {"word": "y"})
    assert result.parsed.echo == "y"
    assert len(fake.messages.calls) == 2
    assert list(LLMCall.objects.order_by("id").values_list("status", flat=True)) == ["invalid_output", "ok"]


def test_invalid_output_twice_raises(score_prompt, fake_anthropic):
    fake_anthropic(message("nope"), message("still nope"))
    with pytest.raises(llm.LLMOutputInvalid) as exc:
        llm.complete("t.score", {"word": "z"})
    assert exc.value.call.status == "invalid_output"
    assert LLMCall.objects.count() == 2


def test_refusal_is_logged_and_raised_without_retry(score_prompt, fake_anthropic):
    details = SimpleNamespace(category="cyber", explanation="no")
    fake = fake_anthropic(message([], stop_reason="refusal", stop_details=details))
    with pytest.raises(llm.LLMRefused, match="cyber"):
        llm.complete("t.score", {"word": "z"})
    assert len(fake.messages.calls) == 1
    assert LLMCall.objects.get().status == "refused"


def test_truncation_raises(score_prompt, fake_anthropic):
    fake_anthropic(message('{"ok": tr', stop_reason="max_tokens"))
    with pytest.raises(llm.LLMTruncated):
        llm.complete("t.score", {"word": "z"})
    assert LLMCall.objects.get().status == "truncated"


def test_api_error_is_logged(score_prompt, fake_anthropic):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_anthropic(anthropic.APIConnectionError(request=request))
    with pytest.raises(llm.LLMError):
        llm.complete("t.score", {"word": "z"})
    assert LLMCall.objects.get().status == "error"


def test_web_search_pause_turn_continues_and_uses_final_text(prompts_tmp, fake_anthropic, settings):
    write_prompt(prompts_tmp, "t.research", "v1",
                 "model_tier: writer\nmax_tokens: 8000\neffort: high\ntools: [web_search]\nweb_search_max_uses: 3",
                 "Research.", "Go")
    paused = message(
        [text_block("Let me search."), SimpleNamespace(type="server_tool_use")],
        stop_reason="pause_turn", usage_=usage(1000, 100, web_search=1),
    )
    done = message(
        [SimpleNamespace(type="web_search_tool_result"), text_block("# Competitors\n"), text_block("A and B.")],
        usage_=usage(3000, 400, web_search=2),
    )
    fake = fake_anthropic(paused, done)

    result = llm.complete("t.research")

    assert result.text == "# Competitors\nA and B."
    first = fake.messages.calls[0]
    assert first["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
    assert first["output_config"] == {"effort": "high"}
    assert first["model"] == settings.LLM_MODELS["writer"]
    second = fake.messages.calls[1]
    assert second["messages"][-1]["role"] == "assistant"
    call = LLMCall.objects.get()
    assert (call.input_tokens, call.output_tokens, call.web_search_requests) == (4000, 500, 3)


def test_extra_cached_block_gets_the_breakpoint(score_prompt, fake_anthropic):
    fake = fake_anthropic(message('{"ok": true, "echo": "x"}'))
    llm.complete("t.score", {"word": "x"}, extra_cached="<page>site</page>")
    system = fake.messages.calls[0]["system"]
    assert "cache_control" not in system[0]  # guardrails: covered by the later breakpoint
    assert system[1] == {"type": "text", "text": "<page>site</page>", "cache_control": {"type": "ephemeral"}}
    assert system[2] == {"type": "text", "text": "Score things."}


def test_no_guardrails_no_context_has_no_cached_block(prompts_tmp, fake_anthropic):
    fm = "model_tier: fast\nschema: SmokeResult\ninclude_guardrails: false\ninclude_context: false"
    write_prompt(prompts_tmp, "t.bare", "v1", fm, "Bare.", "Go")
    fake = fake_anthropic(message('{"ok": true, "echo": "x"}'))
    llm.complete("t.bare")
    assert fake.messages.calls[0]["system"] == [{"type": "text", "text": "Bare."}]


def test_auth_error_is_config_error_not_llm_error(score_prompt, fake_anthropic):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(401, request=request)
    fake_anthropic(anthropic.AuthenticationError("bad key", response=response, body=None))
    with pytest.raises(llm.LLMConfigError):
        llm.complete("t.score", {"word": "z"})
    assert not issubclass(llm.LLMConfigError, llm.LLMError)
    assert LLMCall.objects.get().status == "error"


def test_missing_key_fails_before_any_call(score_prompt, settings):
    from llm import client as llm_client

    llm_client.set_client(None)
    settings.ANTHROPIC_API_KEY = ""
    with pytest.raises(llm.LLMConfigError, match="ANTHROPIC_API_KEY"):
        llm.complete("t.score", {"word": "z"})
    assert LLMCall.objects.count() == 0
