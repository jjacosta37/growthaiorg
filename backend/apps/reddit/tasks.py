from celery import shared_task
from django.conf import settings

from apps.agents.models import AgentRun
from apps.agents.runs import RunReporter, running
from llm import batch as llm_batch
from llm.models import LLMBatch

from . import pipeline


@shared_task
def poll_scoring_batch(run_id: int) -> None:
    """Re-checks the scoring batch until it ends, then finishes the run (scores → drafts)."""
    run = AgentRun.objects.select_related("project").get(pk=run_id)
    if run.status != AgentRun.Status.WAITING_BATCH:
        return
    b = LLMBatch.objects.get(pk=run.params["batch_id"])
    if not llm_batch.is_done(b):
        if pipeline.batch_expired(run):
            with running(run):
                raise RuntimeError(f"Scoring batch {b.anthropic_batch_id} didn't finish in time")
        poll_scoring_batch.apply_async((run_id,), countdown=settings.LLM_BATCH_POLL_SECONDS)
        return
    with running(run) as reporter:
        pipeline.finish_batch_run(run, reporter)


__all__ = ["poll_scoring_batch", "RunReporter"]
