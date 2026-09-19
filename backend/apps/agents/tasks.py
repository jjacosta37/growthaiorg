import logging

from celery import shared_task

from apps.core.models import Project

from . import registry
from .models import AgentConfig, AgentRun
from .runs import RunConflict, create_run, running

log = logging.getLogger(__name__)


@shared_task
def run_agent_task(run_id: int) -> None:
    run = AgentRun.objects.select_related("project").get(pk=run_id)
    spec = registry.get(run.kind)
    with running(run) as reporter:
        spec.run(run, reporter)


@shared_task
def run_scheduled_agent(project_id: int, agent_type: str) -> None:
    """Entry point for celery beat (one PeriodicTask per enabled agent)."""
    project = Project.objects.get(pk=project_id)
    config = AgentConfig.for_project(project, agent_type)
    if not config.enabled:
        return
    try:
        run = create_run(project, agent_type, trigger=AgentRun.Trigger.SCHEDULED)
    except RunConflict:
        log.info("skipping scheduled %s run: previous run still active", agent_type)
        return
    run_agent_task(run.id)


@shared_task
def regenerate_draft_task(run_id: int) -> None:
    from apps.inbox.models import Draft

    run = AgentRun.objects.select_related("project").get(pk=run_id)
    with running(run) as reporter:
        draft = Draft.objects.get(pk=run.params["draft_id"], project=run.project)
        reporter.step(f"Regenerating draft #{draft.pk}")
        registry.get(draft.agent_type).regenerate(
            draft, run.params.get("nudge", ""), run.params.get("instruction", ""), run
        )
        reporter.success("Regenerated")
