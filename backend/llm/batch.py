"""Message Batches API: 50% cheaper, results within 24h (usually minutes). For non-urgent,
high-volume work such as relevance scoring. Callers submit, then poll `is_done()` from a Celery
task, then `collect()`. Manual "run now" triggers use llm.complete() instead.
"""

import logging
from dataclasses import dataclass

import anthropic
from django.utils import timezone
from pydantic import BaseModel

from .client import _finish, _Usage, build_params, get_client, interpret_response, output_schema
from .errors import LLMConfigError, LLMError
from .models import LLMBatch, LLMCall
from .prompts import load_prompt
from .tracing import traceable

log = logging.getLogger(__name__)


@dataclass
class BatchItemResult:
    custom_id: str
    ok: bool
    parsed: BaseModel | None
    text: str
    error: str
    call: LLMCall


@traceable(run_type="chain", name="llm.batch.submit")
def submit(task: str, items: list[tuple[str, dict]], *, project=None, run=None, meta=None) -> LLMBatch:
    """items: (custom_id, variables). custom_id must match ^[a-zA-Z0-9_-]{1,64}$ and be unique."""
    if not items:
        raise ValueError("Empty batch")
    spec = load_prompt(task)
    requests = [{"custom_id": cid, "params": build_params(spec, variables, project)} for cid, variables in items]
    try:
        batch = get_client().messages.batches.create(requests=requests)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.CredentialsError) as exc:
        raise LLMConfigError(f"Anthropic rejected the credentials: {exc}") from exc
    except anthropic.AnthropicError as exc:
        raise LLMError(f"{task}: batch submit failed: {exc}") from exc
    return LLMBatch.objects.create(
        project=project, agent_run=run, anthropic_batch_id=batch.id, task=task, prompt_version=spec.version,
        model=requests[0]["params"]["model"], request_count=len(requests), meta=meta or {},
    )


def is_done(llm_batch: LLMBatch) -> bool:
    """True once Anthropic has finished processing (results can be collected)."""
    if llm_batch.status != LLMBatch.Status.SUBMITTED:
        return True
    remote = get_client().messages.batches.retrieve(llm_batch.anthropic_batch_id)
    if remote.processing_status == "ended":
        llm_batch.status = LLMBatch.Status.ENDED
        llm_batch.ended_at = timezone.now()
        llm_batch.save(update_fields=["status", "ended_at"])
        return True
    return False


@traceable(run_type="chain", name="llm.batch.collect")
def collect(llm_batch: LLMBatch) -> dict[str, BatchItemResult]:
    """Fetch every result, log one LLMCall per request (batch-discounted), return them by custom_id.

    Results arrive in any order, so they're always keyed by custom_id, never by position.
    """
    spec = load_prompt(llm_batch.task, llm_batch.prompt_version)
    schema = output_schema(spec)
    out: dict[str, BatchItemResult] = {}
    for item in get_client().messages.batches.results(llm_batch.anthropic_batch_id):
        call = LLMCall(
            project=llm_batch.project, agent_run=llm_batch.agent_run, task=llm_batch.task, model=llm_batch.model,
            prompt_version=spec.version, prompt_hash=spec.hash, batch=llm_batch, custom_id=item.custom_id,
        )
        usage = _Usage()
        result = item.result
        if result.type == "succeeded":
            message = result.message
            usage.add(message.usage)
            call.stop_reason = message.stop_reason or ""
            outcome = interpret_response(spec, schema, message)
            _finish(call, usage, None, outcome.status, error=outcome.error, is_batch=True)
            ok, parsed, text, error = outcome.status == LLMCall.Status.OK, outcome.parsed, outcome.text, outcome.error
        else:
            detail = getattr(getattr(result, "error", None), "error", None) or getattr(result, "error", None)
            error = f"batch item {result.type}: {detail}" if detail else f"batch item {result.type}"
            _finish(call, usage, None, LLMCall.Status.ERROR, error=error, is_batch=True)
            ok, parsed, text = False, None, ""
        out[item.custom_id] = BatchItemResult(item.custom_id, ok, parsed, text, error, call)

    llm_batch.status = LLMBatch.Status.COLLECTED
    llm_batch.collected_at = timezone.now()
    llm_batch.succeeded_count = sum(r.ok for r in out.values())
    llm_batch.errored_count = len(out) - llm_batch.succeeded_count
    llm_batch.save(update_fields=["status", "collected_at", "succeeded_count", "errored_count"])
    return out
