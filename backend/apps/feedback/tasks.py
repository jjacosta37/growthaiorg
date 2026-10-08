import logging

from celery import shared_task

from apps.agents.models import AgentRun
from apps.agents.runs import RunConflict, create_run, running
from apps.core.models import Project

from .pipeline import digest_feedback
from .services import pending, schedule_digest

log = logging.getLogger(__name__)


def start_digest(project: Project, agent_type: str, *, rebuild: bool = False) -> AgentRun:
    """Create a queued digest run for the project.

    Args:
        rebuild: Re-learn from all feedback, replacing the learnings, instead of folding in
            only the pending entries.

    Raises:
        RunConflict: A digest is already active for the project. Only one runs at a time, which
            is what bounds digest spend.
    """
    return create_run(project, AgentRun.Kind.DIGEST_FEEDBACK, params={"agent_type": agent_type, "rebuild": rebuild})


@shared_task
def digest_feedback_task(project_id: int, agent_type: str) -> None:
    """Fold in whatever feedback is still pending; scheduled after new feedback arrives.

    Does nothing if an earlier digest already took the entries, or if a digest is running (that
    one reschedules itself when it ends with entries still pending).

    Args:
        project_id: The project the feedback belongs to. It comes from server code only.
        agent_type: The agent whose learnings to update.
    """
    project = Project.objects.get(pk=project_id)
    if not pending(project, agent_type).exists():
        return  # an earlier digest already folded these in
    try:
        run = start_digest(project, agent_type)
    except RunConflict:
        # The active digest re-schedules itself if entries are still pending when it ends.
        log.info("feedback digest for project %s (%s) deferred: a digest is already running",
                 project_id, agent_type)
        return
    run_digest_task(run.id)


@shared_task
def run_digest_task(run_id: int) -> None:
    """Execute a queued digest run, then schedule another if more feedback arrived meanwhile.

    Args:
        run_id: A `digest_feedback` `AgentRun`, created by `start_digest`.
    """
    run = AgentRun.objects.select_related("project").get(pk=run_id)
    agent_type = run.params["agent_type"]
    with running(run) as reporter:
        digest_feedback(run, reporter)
    # Outside `running()`, so the finished run no longer blocks the next one.
    run.refresh_from_db(fields=["status"])
    if run.status == AgentRun.Status.SUCCEEDED and pending(run.project, agent_type).exists():
        log.info("feedback digest for project %s (%s): more feedback arrived, scheduling another",
                 run.project_id, agent_type)
        schedule_digest(run.project_id, agent_type)
