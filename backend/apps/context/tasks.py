from celery import shared_task

from apps.agents.models import AgentRun
from apps.agents.runs import running

from . import pipeline


@shared_task
def onboarding_task(run_id: int) -> None:
    run = AgentRun.objects.select_related("project").get(pk=run_id)
    with running(run) as reporter:
        pipeline.run_onboarding(run, reporter)


@shared_task
def regenerate_document_task(run_id: int) -> None:
    run = AgentRun.objects.select_related("project").get(pk=run_id)
    with running(run) as reporter:
        pipeline.run_regenerate_document(run, reporter)
