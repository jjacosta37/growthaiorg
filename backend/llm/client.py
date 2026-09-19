"""Synchronous calls. See llm/batch.py for the Message Batches path."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from django.conf import settings
from pydantic import BaseModel, ValidationError

from .context import build_system
from .errors import LLMConfigError, LLMError, LLMOutputInvalid, LLMRefused, LLMTruncated
from .models import LLMCall
from .pricing import compute_cost
from .prompts import PromptSpec, load_prompt
from .schemas import get_schema
from .tracing import current_run_id, traceable, wrap_client

log = logging.getLogger(__name__)

WEB_SEARCH_TOOL = "web_search_20260209"
MAX_PAUSE_TURNS = 5

_client = None


def get_client():
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set")
        raw = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY or None,
            max_retries=settings.LLM_MAX_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        _client = wrap_client(raw)
    return _client


def set_client(client) -> None:
    """Swap the client (tests inject a fake here)."""
    global _client
    _client = client


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    call: LLMCall
    model: str
    prompt_version: str

    @property
    def task(self) -> str:
        return self.call.task


def model_for(spec: PromptSpec) -> str:
    return settings.LLM_MODELS[spec.model_tier]


def output_schema(spec: PromptSpec) -> type[BaseModel] | None:
    return get_schema(spec.schema) if spec.schema else None


def build_params(spec: PromptSpec, variables: dict, project, extra_cached: str | None = None) -> dict[str, Any]:
    """Request params for messages.create. Shared by the sync and batch paths."""
    system_text, user_text = spec.render(variables)
    params: dict[str, Any] = {
        "model": model_for(spec),
        "max_tokens": spec.max_tokens,
        "system": build_system(
            project,
            system_text,
            include_guardrails=spec.include_guardrails,
            include_context=spec.include_context,
            extra_cached=extra_cached,
        ),
        "messages": [{"role": "user", "content": user_text}],
    }
    output_config: dict[str, Any] = {}
    if spec.effort:
        output_config["effort"] = spec.effort
    if schema := output_schema(spec):
        output_config["format"] = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
    if output_config:
        params["output_config"] = output_config
    if "web_search" in spec.tools:
        params["tools"] = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": spec.web_search_max_uses}]
    return params


def response_text(content) -> str:
    """Final answer text. With server tools the response interleaves text and tool blocks;
    the answer is the text after the last tool result."""
    last_tool_idx = -1
    for i, block in enumerate(content):
        if block.type.endswith("_tool_result") or block.type == "server_tool_use":
            last_tool_idx = i
    texts = [b.text for b in content[last_tool_idx + 1 :] if b.type == "text"]
    return "".join(texts).strip()


def parse_output(schema: type[BaseModel] | None, text: str) -> BaseModel | None:
    if schema is None:
        return None
    return schema.model_validate_json(text)


class _Usage:
    def __init__(self):
        self.input = self.output = self.cache_read = self.cache_write = self.web_search = 0

    def add(self, usage) -> None:
        self.input += usage.input_tokens or 0
        self.output += usage.output_tokens or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        if stu is not None:
            self.web_search += getattr(stu, "web_search_requests", 0) or 0


def complete(
    task: str,
    variables: dict | None = None,
    *,
    project=None,
    run=None,
    version: str | None = None,
    extra_cached: str | None = None,
) -> LLMResult:
    """Run one prompt task and return validated output.

    `run` links the LLMCall to an AgentRun. `extra_cached` is large shared input placed in the
    cached system prefix (after guardrails/context docs, before task instructions).

    Raises LLMRefused / LLMTruncated / LLMOutputInvalid / LLMError. A failed call is still
    logged as an LLMCall row, attached to the exception as `.call`.
    """
    spec = load_prompt(task, version)
    variables = variables or {}
    schema = output_schema(spec)

    last_error: LLMOutputInvalid | None = None
    for attempt in range(2):  # one extra attempt only for schema-invalid output
        try:
            return _traced_attempt(
                spec, variables, project, schema, run, extra_cached,
                langsmith_extra={"name": task, "metadata": {"prompt_version": spec.version, "attempt": attempt}},
            )
        except LLMOutputInvalid as exc:
            log.warning("llm %s %s: invalid structured output (attempt %s)", task, spec.version, attempt + 1)
            last_error = exc
    raise last_error


def _trace_inputs(inputs: dict) -> dict:
    return {"task": inputs["spec"].task, "version": inputs["spec"].version, "variables": inputs["variables"]}


@traceable(run_type="chain", process_inputs=_trace_inputs)
def _traced_attempt(spec, variables, project, schema, run, extra_cached) -> LLMResult:
    return _attempt(spec, variables, project, schema, run, extra_cached)


def _attempt(spec: PromptSpec, variables: dict, project, schema, run, extra_cached) -> LLMResult:
    client = get_client()
    params = build_params(spec, variables, project, extra_cached)
    usage = _Usage()
    call = LLMCall(
        project=project,
        agent_run=run,
        task=spec.task,
        model=params["model"],
        prompt_version=spec.version,
        prompt_hash=spec.hash,
        langsmith_run_id=current_run_id(),
    )
    started = time.monotonic()
    try:
        response = client.messages.create(**params)
        usage.add(response.usage)
        # Server tools (web search) can pause a long turn; resend to let it continue.
        pauses = 0
        while response.stop_reason == "pause_turn" and pauses < MAX_PAUSE_TURNS:
            pauses += 1
            params["messages"] = [*params["messages"], {"role": "assistant", "content": response.content}]
            response = client.messages.create(**params)
            usage.add(response.usage)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.CredentialsError) as exc:
        _finish(call, usage, started, LLMCall.Status.ERROR, error=f"{type(exc).__name__}: {exc}")
        raise LLMConfigError(f"Anthropic rejected the credentials: {exc}") from exc
    except anthropic.AnthropicError as exc:
        _finish(call, usage, started, LLMCall.Status.ERROR, error=f"{type(exc).__name__}: {exc}")
        raise LLMError(f"{spec.task}: API error: {exc}", call=call) from exc

    call.stop_reason = response.stop_reason or ""
    call.request_id = getattr(response, "_request_id", None) or ""
    outcome = interpret_response(spec, schema, response)
    _finish(call, usage, started, outcome.status, error=outcome.error)
    outcome.raise_for_status(spec, call)
    return LLMResult(text=outcome.text, parsed=outcome.parsed, call=call, model=call.model,
                     prompt_version=spec.version)


@dataclass
class Outcome:
    """How a finished response turned out. Shared by the sync and batch paths."""

    status: str
    text: str = ""
    parsed: BaseModel | None = None
    error: str = ""

    def raise_for_status(self, spec: PromptSpec, call: LLMCall) -> None:
        if self.status == LLMCall.Status.OK:
            return
        exc_class = {
            LLMCall.Status.REFUSED: LLMRefused,
            LLMCall.Status.TRUNCATED: LLMTruncated,
            LLMCall.Status.INVALID_OUTPUT: LLMOutputInvalid,
        }.get(self.status, LLMError)
        raise exc_class(f"{spec.task}: {self.error}", call=call)


def interpret_response(spec: PromptSpec, schema, response) -> Outcome:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        msg = f"refused ({getattr(details, 'category', None)}): {getattr(details, 'explanation', '')}"
        return Outcome(LLMCall.Status.REFUSED, error=msg)
    if response.stop_reason == "max_tokens":
        return Outcome(LLMCall.Status.TRUNCATED, error=f"output truncated at max_tokens={spec.max_tokens}")
    if response.stop_reason == "pause_turn":
        return Outcome(LLMCall.Status.ERROR, error=f"turn still paused after {MAX_PAUSE_TURNS} continuations")
    text = response_text(response.content)
    try:
        parsed = parse_output(schema, text)
    except (ValidationError, json.JSONDecodeError) as exc:
        return Outcome(LLMCall.Status.INVALID_OUTPUT, text=text,
                       error=f"output failed schema {spec.schema}: {str(exc)[:1500]}")
    return Outcome(LLMCall.Status.OK, text=text, parsed=parsed)


def _finish(call: LLMCall, usage: _Usage, started: float | None, status: str, error: str = "",
            is_batch: bool = False) -> None:
    call.status = status
    call.error = error
    call.is_batch = is_batch
    if started is not None:
        call.latency_ms = int((time.monotonic() - started) * 1000)
    call.input_tokens = usage.input
    call.output_tokens = usage.output
    call.cache_read_tokens = usage.cache_read
    call.cache_write_tokens = usage.cache_write
    call.web_search_requests = usage.web_search
    call.cost_usd = compute_cost(
        call.model,
        input_tokens=usage.input,
        output_tokens=usage.output,
        cache_read_tokens=usage.cache_read,
        cache_write_tokens=usage.cache_write,
        web_search_requests=usage.web_search,
        is_batch=is_batch,
    )
    call.save()
