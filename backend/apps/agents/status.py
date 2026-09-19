from .models import AgentRun


def active_runs_status(project) -> dict:
    runs = list(
        AgentRun.objects.filter(project=project, status__in=AgentRun.ACTIVE).order_by("created_at")[:10]
    )
    active = [
        {"id": r.id, "kind": r.kind, "status": r.status, "current_step": r.current_step} for r in runs
    ]
    message = next((r["current_step"] for r in reversed(active) if r["current_step"]), None)
    return {"active": active, "message": message}
