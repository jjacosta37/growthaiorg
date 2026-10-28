"""Agent schedules: the structured choices the UI offers, and how they become celery beat entries.

A schedule is stored as plain choices (every N hours, daily, chosen weekdays, weekly, monthly) in
local time, and the project's timezone says which local time. A schedule may need several beat
entries, because times of day with different minutes can't share one crontab. `custom` exists only
for crons written before the builder; it keeps running but can't be saved again.

Beat's DatabaseScheduler picks up PeriodicTask changes without a restart, and evaluates each
CrontabSchedule in its own timezone, following daylight saving.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, available_timezones

from celery.schedules import crontab as celery_crontab
from django.db.models import Q
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

log = logging.getLogger(__name__)

TASK = "apps.agents.tasks.run_scheduled_agent"

MIN_GAP_MINUTES = 60
MAX_TIMES = 4
DEFAULT_TIMEZONE = "UTC"
# How far ahead next_runs looks. A monthly schedule needs a month; this leaves room for a
# hand-written cron that matches a rare date.
_HORIZON_DAYS = 400

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
Time = Annotated[str, Field(pattern=TIME_PATTERN, description="Local time of day, HH:MM (24h)")]
Weekday = Annotated[int, Field(ge=0, le=6, description="0 = Sunday … 6 = Saturday")]

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class InvalidSchedule(ValueError):
    """The schedule can't be saved: malformed, too frequent, or a custom cron."""


def _minutes(t: str) -> int:
    hour, minute = t.split(":")
    return int(hour) * 60 + int(minute)


def _check_times(times: list[str]) -> list[str]:
    """Distinct, at most four, and at least an hour apart around the clock (23:30 → 00:00 counts)."""
    if len(set(times)) != len(times):
        raise ValueError("Each time of day can only be listed once")
    ordered = sorted(times, key=_minutes)
    marks = [_minutes(t) for t in ordered]
    gaps = [b - a for a, b in zip(marks, marks[1:], strict=False)]
    if len(marks) > 1:
        gaps.append(marks[0] + 24 * 60 - marks[-1])
    if any(g < MIN_GAP_MINUTES for g in gaps):
        raise ValueError("Agent schedules can run at most once an hour; space the times at least an hour apart")
    return ordered


class EveryHours(BaseModel):
    """Every N hours, at a fixed minute past the hour. N divides 24, so runs stay evenly spaced."""

    kind: Literal["every_hours"]
    hours: Literal[1, 2, 3, 4, 6, 8, 12]
    minute: int = Field(0, ge=0, le=59)


class Daily(BaseModel):
    """Every day at one to four times."""

    kind: Literal["daily"]
    times: list[Time] = Field(min_length=1, max_length=MAX_TIMES)

    @field_validator("times")
    @classmethod
    def spaced_times(cls, v: list[str]) -> list[str]:
        """Distinct and at least an hour apart."""
        return _check_times(v)


class Weekdays(BaseModel):
    """On the chosen days of the week, at one to four times."""

    kind: Literal["weekdays"]
    days: list[Weekday] = Field(min_length=1, max_length=7)
    times: list[Time] = Field(min_length=1, max_length=MAX_TIMES)

    @field_validator("times")
    @classmethod
    def spaced_times(cls, v: list[str]) -> list[str]:
        """Distinct and at least an hour apart."""
        return _check_times(v)

    @field_validator("days")
    @classmethod
    def distinct_days(cls, v: list[int]) -> list[int]:
        """Sorted, without repeats."""
        return sorted(set(v))


class Weekly(BaseModel):
    """Once a week."""

    kind: Literal["weekly"]
    day: Weekday
    time: Time


class Monthly(BaseModel):
    """Once a month. Days 1–28 only, so no month is skipped."""

    kind: Literal["monthly"]
    day: int = Field(ge=1, le=28)
    time: Time


class Custom(BaseModel):
    """A cron written before the builder existed. Read-only: it keeps running but can't be saved."""

    kind: Literal["custom"]
    cron: str

    @field_validator("cron")
    @classmethod
    def valid_cron(cls, v: str) -> str:
        """Five fields celery accepts."""
        parse_cron(v)
        return v.strip()


Schedule = Annotated[EveryHours | Daily | Weekdays | Weekly | Monthly | Custom, Field(discriminator="kind")]
_adapter: TypeAdapter = TypeAdapter(Schedule)


def parse_schedule(data: dict) -> BaseModel:
    """Validate stored or submitted schedule JSON.

    Raises:
        InvalidSchedule: with a readable message per problem.
    """
    try:
        return _adapter.validate_python(data)
    except ValidationError as exc:
        raise InvalidSchedule("; ".join(_message(e) for e in exc.errors(include_url=False))) from exc


def writable_schedule(data: dict) -> BaseModel:
    """A schedule a user may save: any builder kind, never `custom`.

    Refusing `custom` here is what makes the hourly minimum hold for direct API calls too.

    Raises:
        InvalidSchedule: when the schedule is malformed, too frequent, or custom.
    """
    if isinstance(data, dict) and data.get("kind") == "custom":
        raise InvalidSchedule("Custom schedules can't be saved; choose how often the agent runs")
    return parse_schedule(data)


def _message(error: dict) -> str:
    msg = error["msg"].removeprefix("Value error, ")
    if error["type"] == "string_pattern_mismatch":
        msg = "Use times of day as HH:MM (24-hour)"
    if error["type"] == "value_error":
        return msg  # our own messages read on their own
    loc = [str(p) for p in error["loc"] if not isinstance(p, int) and p not in _KINDS]
    return f"{'.'.join(loc)}: {msg}" if loc else msg


_KINDS = {"every_hours", "daily", "weekdays", "weekly", "monthly", "custom"}


# Files tzdata ships that aren't places: "localtime" would reveal the server's own offset.
_PSEUDO_ZONES = {"localtime", "Factory"}


def valid_timezone(name: str) -> str:
    """An IANA timezone name.

    Raises:
        InvalidSchedule: when the name isn't a known zone.
    """
    if name in _PSEUDO_ZONES or name not in available_timezones():
        raise InvalidSchedule(f"Unknown timezone {name!r}")
    return name


# --------------------------------------------------------------------------- crontab entries


def parse_cron(expr: str) -> dict:
    """A five-field cron as CrontabSchedule field kwargs.

    Raises:
        InvalidSchedule: when it isn't five fields celery accepts.
    """
    parts = expr.split()
    if len(parts) != 5:
        raise InvalidSchedule("Use 5 fields: minute hour day-of-month month day-of-week")
    minute, hour, dom, month, dow = parts
    fields = {"minute": minute, "hour": hour, "day_of_month": dom, "month_of_year": month, "day_of_week": dow}
    try:
        celery_crontab(**fields)
    except (ValueError, TypeError) as exc:
        raise InvalidSchedule(str(exc)) from exc
    return fields


def _entry(minute: int | str, hour: str, dow: str = "*", dom: str = "*") -> dict:
    return {"minute": str(minute), "hour": hour, "day_of_month": dom, "month_of_year": "*", "day_of_week": dow}


def _by_minute(times: list[str]) -> dict[int, list[int]]:
    """{minute: [hours]}: times sharing a minute share one crontab entry."""
    grouped: dict[int, list[int]] = {}
    for t in times:
        hour, minute = (int(x) for x in t.split(":"))
        grouped.setdefault(minute, []).append(hour)
    return dict(sorted(grouped.items()))


def to_entries(schedule: BaseModel) -> list[dict]:
    """The crontab entries (CrontabSchedule field kwargs) that together make up the schedule."""
    match schedule:
        case EveryHours(hours=1, minute=m):
            return [_entry(m, "*")]
        case EveryHours(hours=n, minute=m):
            return [_entry(m, f"*/{n}")]
        case Daily(times=times):
            return [_entry(m, ",".join(map(str, sorted(hs)))) for m, hs in _by_minute(times).items()]
        case Weekdays(days=days, times=times):
            dow = ",".join(map(str, days))
            return [_entry(m, ",".join(map(str, sorted(hs))), dow) for m, hs in _by_minute(times).items()]
        case Weekly(day=day, time=t):
            hour, minute = t.split(":")
            return [_entry(int(minute), str(int(hour)), str(day))]
        case Monthly(day=day, time=t):
            hour, minute = t.split(":")
            return [_entry(int(minute), str(int(hour)), dom=str(day))]
        case Custom(cron=cron):
            return [parse_cron(cron)]
    raise InvalidSchedule(f"Unknown schedule {schedule!r}")


# --------------------------------------------------------------------------- reading old crons


def _int_list(field: str, lo: int, hi: int) -> list[int] | None:
    """'1,3,5' or '1-5' (or a mix) as ints, or None for anything else."""
    out: list[int] = []
    for part in field.split(","):
        bounds = part.split("-")
        if not all(b.isdigit() for b in bounds) or len(bounds) > 2:
            return None
        a, b = int(bounds[0]), int(bounds[-1])
        if a > b:
            return None
        out.extend(range(a, b + 1))
    if not out or any(not lo <= v <= hi for v in out):
        return None
    return out


def from_cron(expr: str) -> dict:
    """The builder schedule a cron expresses, or `custom` when it isn't one of the builder's shapes.

    Used to move crons saved before the builder over without changing when they fire.
    """
    custom = {"kind": "custom", "cron": " ".join(expr.split())}
    parts = expr.split()
    if len(parts) != 5:
        return custom
    minute, hour, dom, month, dow = parts
    if month != "*" or not minute.isdigit() or not 0 <= int(minute) <= 59:
        return custom
    m = int(minute)
    candidate: dict | None = None

    if hour == "*" and dom == "*" and dow == "*":
        candidate = {"kind": "every_hours", "hours": 1, "minute": m}
    elif hour.startswith("*/") and hour[2:].isdigit() and dom == "*" and dow == "*":
        candidate = {"kind": "every_hours", "hours": int(hour[2:]), "minute": m}
    else:
        hours = _int_list(hour, 0, 23)
        if hours is not None and len(set(hours)) <= MAX_TIMES:
            times = [f"{h:02d}:{m:02d}" for h in sorted(set(hours))]
            if dom == "*" and dow == "*":
                candidate = {"kind": "daily", "times": times}
            elif dom == "*":
                days = _int_list(dow, 0, 7)
                if days is not None:
                    days = sorted({d % 7 for d in days})  # 7 is Sunday too
                    if len(days) == 1 and len(times) == 1:
                        candidate = {"kind": "weekly", "day": days[0], "time": times[0]}
                    else:
                        candidate = {"kind": "weekdays", "days": days, "times": times}
            elif dow == "*" and dom.isdigit() and len(times) == 1:
                candidate = {"kind": "monthly", "day": int(dom), "time": times[0]}

    if candidate is None:
        return custom
    try:
        return parse_schedule(candidate).model_dump()
    except InvalidSchedule:
        return custom


# --------------------------------------------------------------------------- when it runs


def next_runs(schedule: BaseModel, tz: str, n: int = 3, after: datetime | None = None) -> list[datetime]:
    """The next `n` run times (UTC, aware) after `after`, evaluated in local time in `tz`.

    Mirrors how beat reads a crontab: every field must match (celery ANDs day-of-month and
    day-of-week), and a local time that doesn't exist on a daylight-saving change is skipped.
    """
    zone = ZoneInfo(tz)
    after = after or timezone.now()
    crons = [celery_crontab(**fields) for fields in to_entries(schedule)]
    day = after.astimezone(zone).date()
    out: list[datetime] = []
    for _ in range(_HORIZON_DAYS):
        for local in _local_runs(day, crons, zone):
            if local > after:
                out.append(local.astimezone(UTC))
                if len(out) == n:
                    return out
        day += timedelta(days=1)
    return out


def _local_runs(day: date, crons: list, zone: ZoneInfo) -> list[datetime]:
    dow = (day.weekday() + 1) % 7
    slots = {
        (h, m)
        for c in crons
        if day.month in c.month_of_year and day.day in c.day_of_month and dow in c.day_of_week
        for h in c.hour
        for m in c.minute
    }
    runs = []
    for h, m in sorted(slots):
        local = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
        if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None):
            runs.append(local)  # else: inside a spring-forward gap, so it doesn't exist
    return runs


def min_gap(schedule: BaseModel, tz: str) -> timedelta | None:
    """The shortest gap between the next 50 runs, or None if fewer than two are coming up."""
    runs = next_runs(schedule, tz, n=50)
    return min((b - a for a, b in zip(runs, runs[1:], strict=False)), default=None)


def too_frequent(schedule: BaseModel, tz: str) -> bool:
    """True when two upcoming runs are less than an hour apart (only possible for a custom cron)."""
    gap = min_gap(schedule, tz)
    return gap is not None and gap < timedelta(minutes=MIN_GAP_MINUTES)


# --------------------------------------------------------------------------- plain words


def _clock(t: str) -> str:
    hour, minute = (int(x) for x in t.split(":"))
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}:{minute:02d}{suffix}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _days_phrase(days: list[int]) -> str:
    if days == [1, 2, 3, 4, 5]:
        return "Weekdays"
    if days == [0, 6]:
        return "Weekends"
    if len(days) == 7:
        return "Every day"
    order = sorted(days, key=lambda d: (d + 6) % 7)  # Monday first
    return _join([DAY_NAMES[d][:3] for d in order])


def describe(schedule: BaseModel) -> str:
    """The schedule in plain words, without the timezone."""
    match schedule:
        case EveryHours(hours=n, minute=m):
            base = "Every hour" if n == 1 else f"Every {n} hours"
            return base if m == 0 else f"{base} at :{m:02d}"
        case Daily(times=times):
            return f"Every day at {_join([_clock(t) for t in times])}"
        case Weekdays(days=days, times=times):
            return f"{_days_phrase(days)} at {_join([_clock(t) for t in times])}"
        case Weekly(day=day, time=t):
            return f"{DAY_NAMES[day]}s at {_clock(t)}"
        case Monthly(day=day, time=t):
            return f"Monthly on the {_ordinal(day)} at {_clock(t)}"
    return "Custom schedule"


def summary(schedule: BaseModel, tz: str) -> str:
    """Plain words naming the timezone, e.g. "Weekdays at 9:00am and 5:00pm (Europe/Madrid)"."""
    return f"{describe(schedule)} ({tz})"


# --------------------------------------------------------------------------- beat sync


def task_name(config) -> str:
    return f"agent:{config.project_id}:{config.agent_type}"


def _agent_tasks(config):
    base = task_name(config)
    return PeriodicTask.objects.filter(Q(name=base) | Q(name__startswith=f"{base}:"))


def sync_periodic_task(config) -> None:
    """Make beat's entries for one agent match its schedule, enabled flag and project timezone.

    Entry 0 keeps the historical name `agent:<project>:<type>`; extra entries get `:<i>`.
    Entries the schedule no longer needs are deleted.
    """
    tz = config.project.effective_timezone
    entries = to_entries(parse_schedule(config.schedule))
    base = task_name(config)
    names = [base] + [f"{base}:{i}" for i in range(1, len(entries))]
    for name, fields in zip(names, entries, strict=True):
        crontab, _ = CrontabSchedule.objects.get_or_create(**fields, timezone=tz)
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={
                "task": TASK,
                "crontab": crontab,
                "args": json.dumps([config.project_id, config.agent_type]),
                "enabled": config.enabled,
            },
        )
    _agent_tasks(config).exclude(name__in=names).delete()


def sync_project_tasks(project) -> None:
    """Resync every agent of a project, e.g. after its timezone changed."""
    for config in project.agent_configs.select_related("project"):
        sync_periodic_task(config)


def delete_periodic_tasks(project) -> int:
    """Remove a project's beat entries.

    PeriodicTask has no FK to Project, so nothing cascades. Left behind, beat would keep
    firing them and `run_scheduled_agent` would raise Project.DoesNotExist every tick.
    """
    deleted, _ = PeriodicTask.objects.filter(name__startswith=f"agent:{project.pk}:").delete()
    return deleted


def next_run_at(config) -> datetime | None:
    """When the agent next runs, or None while it's disabled."""
    if not config.enabled:
        return None
    try:
        runs = next_runs(parse_schedule(config.schedule), config.project.effective_timezone, n=1)
    except InvalidSchedule:
        log.warning("Agent config %s has an unreadable schedule", config.pk, exc_info=True)
        return None
    return runs[0] if runs else None
