import logging

from celery import shared_task

from apps.agents.models import AgentRun
from apps.agents.runs import RunConflict, create_run, running
from apps.core.models import Project

from .pipeline import digest_feedback
from .services import pending, schedule_digest

log = logging.getLogger(__name__)


@shared_task
def digest_feedback_task(project_id: int, agent_type: str, rebuild: bool = False) -> None:
    project = Project.objects.get(pk=project_id)
    if not rebuild and not pending(project, agent_type).exists():
        return  # an earlier digest already folded these in
    try:
        run = create_run(project, AgentRun.Kind.DIGEST_FEEDBACK,
                         params={"agent_type": agent_type, "rebuild": rebuild})
    except RunConflict:
        # The active digest re-schedules itself if entries are still pending when it ends.
        log.info("feedback digest for project %s (%s) deferred: a digest is already running",
                 project_id, agent_type)
        return
    with running(run) as reporter:
        digest_feedback(run, reporter)
    # Outside `running()`, so the finished run no longer blocks the next one.
    run.refresh_from_db(fields=["status"])
    if run.status == AgentRun.Status.SUCCEEDED and pending(project, agent_type).exists():
        log.info("feedback digest for project %s (%s): more feedback arrived, scheduling another",
                 project_id, agent_type)
        schedule_digest(project_id, agent_type)
