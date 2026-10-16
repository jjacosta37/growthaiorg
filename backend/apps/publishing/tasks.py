from celery import shared_task

from apps.agents.models import AgentRun
from apps.agents.runs import running


@shared_task
def publish_pr_task(run_id: int) -> None:
    """Open or update one blog draft's pull request.

    Args:
        run_id: A `publish_pr` AgentRun whose params hold `draft_id` and `action`
            ("create" or "update"). The draft is loaded scoped to the run's project.
    """
    from apps.inbox.models import Draft

    from . import services

    run = AgentRun.objects.select_related("project").get(pk=run_id)
    with running(run) as reporter:
        draft = Draft.objects.select_related("current_version", "project").get(
            pk=run.params["draft_id"], project=run.project)
        if run.params.get("action") == "update":
            services.update_pull_request(draft, run, reporter)
        else:
            services.open_pull_request(draft, run, reporter)
