"""Keeps celery beat's PeriodicTask rows in sync with AgentConfig (DatabaseScheduler picks up
changes without a restart)."""

import json
from datetime import datetime

from celery.schedules import crontab as celery_crontab
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask

TASK = "apps.agents.tasks.run_scheduled_agent"


class InvalidCron(ValueError):
    pass


def parse_cron(expr: str) -> dict:
    parts = expr.split()
    if len(parts) != 5:
        raise InvalidCron("Use 5 fields: minute hour day-of-month month day-of-week")
    minute, hour, dom, month, dow = parts
    fields = {"minute": minute, "hour": hour, "day_of_month": dom, "month_of_year": month, "day_of_week": dow}
    try:
        celery_crontab(**fields)
    except (ValueError, TypeError) as exc:
        raise InvalidCron(str(exc)) from exc
    return fields


def task_name(config) -> str:
    return f"agent:{config.project_id}:{config.agent_type}"


def sync_periodic_task(config) -> None:
    fields = parse_cron(config.cron)
    schedule, _ = CrontabSchedule.objects.get_or_create(**fields, timezone="UTC")
    PeriodicTask.objects.update_or_create(
        name=task_name(config),
        defaults={
            "task": TASK,
            "crontab": schedule,
            "args": json.dumps([config.project_id, config.agent_type]),
            "enabled": config.enabled,
        },
    )


def next_run_at(config) -> datetime | None:
    if not config.enabled:
        return None
    try:
        fields = parse_cron(config.cron)
    except InvalidCron:
        return None
    now = timezone.now()
    return now + celery_crontab(**fields).remaining_estimate(now)
