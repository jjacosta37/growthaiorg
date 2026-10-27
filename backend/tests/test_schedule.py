"""Agent schedules: the builder's rules, beat entries, timezones, the hourly minimum and old crons."""

from datetime import UTC, datetime
from importlib import import_module

import pytest
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from apps.agents.models import AgentConfig
from apps.agents.schedule import (
    InvalidSchedule,
    from_cron,
    next_runs,
    parse_schedule,
    summary,
    sync_periodic_task,
    to_entries,
    writable_schedule,
)

pytestmark = pytest.mark.django_db

AFTER = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)  # a Friday


def runs(data: dict, tz: str = "UTC", n: int = 3, after: datetime = AFTER) -> list[str]:
    return [t.strftime("%a %d %H:%M") for t in next_runs(parse_schedule(data), tz, n, after)]


# --- The builder's rules (AC-2, AC-3, AC-4, AC-11) ----------------------------------------


@pytest.mark.parametrize("bad", [
    {"kind": "every_hours", "hours": 5},
    {"kind": "every_hours", "hours": 4, "minute": 60},
    {"kind": "daily", "times": []},
    {"kind": "daily", "times": ["01:00", "05:00", "09:00", "13:00", "17:00"]},  # a fifth time
    {"kind": "daily", "times": ["09:00", "09:00"]},
    {"kind": "daily", "times": ["9am"]},
    {"kind": "weekdays", "days": [], "times": ["09:00"]},
    {"kind": "weekdays", "days": [7], "times": ["09:00"]},
    {"kind": "weekly", "day": 1},
    {"kind": "monthly", "day": 29, "time": "09:00"},
    {"kind": "monthly", "day": 0, "time": "09:00"},
    {"kind": "hourly"},
])
def test_builder_refuses_malformed_schedules(bad):
    with pytest.raises(InvalidSchedule):
        writable_schedule(bad)


@pytest.mark.parametrize("times", [["09:00", "09:30"], ["23:30", "00:00"], ["12:00", "12:59"]])
def test_times_less_than_an_hour_apart_are_refused(times):
    with pytest.raises(InvalidSchedule, match="at most once an hour"):
        writable_schedule({"kind": "daily", "times": times})


def test_times_an_hour_apart_are_fine_and_sorted():
    s = writable_schedule({"kind": "weekdays", "days": [5, 1, 1], "times": ["17:00", "09:30", "10:30"]})
    assert s.times == ["09:30", "10:30", "17:00"] and s.days == [1, 5]


def test_custom_can_never_be_saved():
    with pytest.raises(InvalidSchedule, match="Custom schedules"):
        writable_schedule({"kind": "custom", "cron": "0 9 * * *"})


def test_every_n_hours_runs_at_the_same_minute():
    assert runs({"kind": "every_hours", "hours": 4, "minute": 15}) == ["Fri 16 12:15", "Fri 16 16:15", "Fri 16 20:15"]
    assert runs({"kind": "every_hours", "hours": 1, "minute": 0}, n=2) == ["Fri 16 13:00", "Fri 16 14:00"]


def test_each_kind_runs_when_it_says():
    assert runs({"kind": "daily", "times": ["09:00", "17:30"]}) == ["Fri 16 17:30", "Sat 17 09:00", "Sat 17 17:30"]
    assert runs({"kind": "weekdays", "days": [2, 4], "times": ["08:00"]}) == [
        "Tue 20 08:00", "Thu 22 08:00", "Tue 27 08:00"]
    assert runs({"kind": "weekly", "day": 1, "time": "09:00"}, n=2) == ["Mon 19 09:00", "Mon 26 09:00"]
    assert [t.strftime("%m-%d") for t in next_runs(
        parse_schedule({"kind": "monthly", "day": 28, "time": "09:00"}), "UTC", 3, AFTER)] == [
        "10-28", "11-28", "12-28"]


def test_times_with_different_minutes_become_separate_entries():
    entries = to_entries(parse_schedule({"kind": "daily", "times": ["09:00", "17:30", "21:00"]}))
    assert [(e["minute"], e["hour"]) for e in entries] == [("0", "9,21"), ("30", "17")]


# --- Plain words (AC-5) ----------------------------------------------------------------------


@pytest.mark.parametrize("data,words", [
    ({"kind": "every_hours", "hours": 1, "minute": 0}, "Every hour"),
    ({"kind": "every_hours", "hours": 6, "minute": 30}, "Every 6 hours at :30"),
    ({"kind": "daily", "times": ["09:00", "17:00"]}, "Every day at 9:00am and 5:00pm"),
    ({"kind": "weekdays", "days": [1, 2, 3, 4, 5], "times": ["00:00"]}, "Weekdays at 12:00am"),
    ({"kind": "weekdays", "days": [0, 6], "times": ["12:15"]}, "Weekends at 12:15pm"),
    ({"kind": "weekdays", "days": [0, 1, 3], "times": ["08:00"]}, "Mon, Wed and Sun at 8:00am"),
    ({"kind": "weekly", "day": 1, "time": "09:00"}, "Mondays at 9:00am"),
    ({"kind": "monthly", "day": 2, "time": "09:00"}, "Monthly on the 2nd at 9:00am"),
    ({"kind": "custom", "cron": "*/5 * * * *"}, "Custom schedule"),
])
def test_summary_names_the_timezone(data, words):
    assert summary(parse_schedule(data), "Europe/Madrid") == f"{words} (Europe/Madrid)"


# --- Timezones and daylight saving (AC-6, AC-7) --------------------------------------------------


def test_local_time_holds_across_a_daylight_saving_change():
    # Europe/Madrid leaves summer time on 2026-10-25: 9:00 local is 07:00Z before and 08:00Z after.
    utc = [t.isoformat() for t in next_runs(
        parse_schedule({"kind": "daily", "times": ["09:00"]}), "Europe/Madrid", 3,
        datetime(2026, 10, 24, 0, 0, tzinfo=UTC))]
    assert utc == ["2026-10-24T07:00:00+00:00", "2026-10-25T08:00:00+00:00", "2026-10-26T08:00:00+00:00"]


def test_a_local_time_that_does_not_exist_is_skipped():
    # 2026-03-29 02:30 doesn't exist in Madrid (clocks jump from 02:00 to 03:00).
    got = runs({"kind": "daily", "times": ["02:30"]}, "Europe/Madrid", 2, datetime(2026, 3, 28, 12, 0, tzinfo=UTC))
    assert got == ["Mon 30 00:30", "Tue 31 00:30"]


def test_beat_entries_carry_the_project_timezone_and_local_hours(project):
    project.timezone = "America/New_York"
    project.save()
    config = AgentConfig.for_project(project, "x")
    config.schedule = {"kind": "daily", "times": ["09:00", "17:30"]}
    config.enabled = True
    config.save()
    sync_periodic_task(config)

    tasks = PeriodicTask.objects.filter(name__startswith=f"agent:{project.pk}:x").order_by("name")
    assert [t.name for t in tasks] == [f"agent:{project.pk}:x", f"agent:{project.pk}:x:1"]
    assert {(t.crontab.minute, t.crontab.hour, t.crontab.timezone.key) for t in tasks} == {
        ("0", "9", "America/New_York"), ("30", "17", "America/New_York")}

    # Back to one entry: the extra one goes, so beat doesn't keep firing it.
    config.schedule = {"kind": "weekly", "day": 1, "time": "09:00"}
    config.save()
    sync_periodic_task(config)
    assert list(PeriodicTask.objects.filter(name__startswith=f"agent:{project.pk}:x").values_list(
        "name", flat=True)) == [f"agent:{project.pk}:x"]


def test_changing_the_timezone_keeps_local_times_for_every_agent(client, project):
    for agent in ("reddit", "content"):
        client.patch(f"/api/agents/{agent}/", {"enabled": True}, format="json")
    resp = client.patch("/api/agents/content/", {"timezone": "Europe/Madrid"}, format="json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "Europe/Madrid" and data["timezone_set"] is True
    assert data["schedule_summary"] == "Mondays at 9:00am (Europe/Madrid)"

    for agent, hour in (("reddit", "*/4"), ("content", "9")):
        task = PeriodicTask.objects.get(name=f"agent:{project.pk}:{agent}")
        assert (task.crontab.hour, task.crontab.timezone.key) == (hour, "Europe/Madrid")


@pytest.mark.parametrize("zone", ["Mars/Olympus", "localtime", "Factory"])
def test_unknown_timezone_is_refused(client, zone):
    resp = client.patch("/api/agents/reddit/", {"timezone": zone}, format="json")
    assert resp.status_code == 400 and "timezone" in resp.json()


# --- API: saving and previewing (AC-1, AC-5, AC-11) ---------------------------------------------


@pytest.mark.parametrize("schedule", [
    {"kind": "every_hours", "hours": 2, "minute": 0},
    {"kind": "daily", "times": ["08:00", "20:00"]},
    {"kind": "weekdays", "days": [1, 3, 5], "times": ["10:00"]},
    {"kind": "weekly", "day": 0, "time": "18:00"},
    {"kind": "monthly", "day": 15, "time": "07:45"},
])
def test_every_builder_kind_can_be_saved(client, schedule):
    resp = client.patch("/api/agents/x/", {"schedule": schedule}, format="json")
    assert resp.status_code == 200, resp.json()
    assert resp.json()["schedule"] == parse_schedule(schedule).model_dump()


@pytest.mark.parametrize("schedule", [
    {"kind": "daily", "times": ["09:00", "09:30"]},
    {"kind": "custom", "cron": "* * * * *"},
    {"kind": "every_hours", "hours": 5},
])
def test_the_api_refuses_schedules_the_builder_would(client, project, schedule):
    before = AgentConfig.for_project(project, "reddit").schedule
    resp = client.patch("/api/agents/reddit/", {"schedule": schedule}, format="json")
    assert resp.status_code == 400 and resp.json()["schedule"]
    assert AgentConfig.for_project(project, "reddit").schedule == before


def test_preview_describes_without_saving(client, project):
    before = AgentConfig.for_project(project, "reddit").schedule
    resp = client.post("/api/agents/schedule-preview/", {
        "schedule": {"kind": "weekdays", "days": [1, 2, 3, 4, 5], "times": ["09:00", "17:00"]},
        "timezone": "Europe/Madrid",
    }, format="json")
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Weekdays at 9:00am and 5:00pm (Europe/Madrid)"
    assert len(resp.json()["next_runs"]) == 3
    assert AgentConfig.for_project(project, "reddit").schedule == before
    project.refresh_from_db()
    assert project.timezone == ""

    bad = client.post("/api/agents/schedule-preview/", {"schedule": {"kind": "daily", "times": ["09:00", "09:10"]}},
                      format="json")
    assert bad.status_code == 400 and "once an hour" in bad.json()["schedule"][0]


# --- Schedules saved before the builder (AC-9, AC-10, AC-12) ------------------------------------


@pytest.mark.parametrize("cron,kind", [
    ("0 * * * *", "every_hours"),
    ("0 */4 * * *", "every_hours"),
    ("0 */12 * * *", "every_hours"),
    ("0 9 * * *", "daily"),
    ("0 14 * * 1-5", "weekdays"),
    ("0 9 * * 1", "weekly"),
    ("30 9 1 * *", "monthly"),
    ("0 9,17 * * 0,6", "weekdays"),
    ("15 */3 * * *", "every_hours"),
    ("*/30 * * * *", "custom"),
    ("0 9 1,15 * *", "custom"),
    ("0 */5 * * *", "custom"),
    ("0 9 31 * *", "custom"),
])
def test_old_crons_keep_firing_at_the_same_moments(cron, kind):
    schedule = from_cron(cron)
    assert schedule["kind"] == kind
    custom = parse_schedule({"kind": "custom", "cron": cron})
    assert next_runs(parse_schedule(schedule), "UTC", 20, AFTER) == next_runs(custom, "UTC", 20, AFTER)


def test_migration_moves_crons_over(project):
    migration = import_module("apps.agents.migrations.0007_agentconfig_schedule")

    class FakeConfig:
        def __init__(self, cron):
            self.cron, self.schedule = cron, None

        def save(self, update_fields):
            pass

    configs = [FakeConfig("0 9 * * 1"), FakeConfig("*/15 * * * *")]

    class FakeApps:
        def get_model(self, app, name):
            return type("M", (), {"objects": type("Q", (), {"all": staticmethod(lambda: configs)})})

    migration.crons_to_schedules(FakeApps(), None)
    assert configs[0].schedule == {"kind": "weekly", "day": 1, "time": "09:00"}
    assert configs[1].schedule == {"kind": "custom", "cron": "*/15 * * * *"}


def test_a_custom_schedule_keeps_running_and_is_flagged_when_too_frequent(client, project):
    config = AgentConfig.for_project(project, "reddit")
    config.schedule = {"kind": "custom", "cron": "*/15 * * * *"}
    config.enabled = True
    config.save()
    sync_periodic_task(config)

    data = client.get("/api/agents/reddit/").json()
    assert data["schedule"]["kind"] == "custom" and data["schedule_summary"] == "Custom schedule (UTC)"
    assert data["schedule_warning"] == "too_frequent" and len(data["next_runs"]) == 3
    task = PeriodicTask.objects.get(name=f"agent:{project.pk}:reddit")
    assert task.enabled and task.crontab.minute == "*/15"

    # Other settings still save, and leave the schedule alone.
    assert client.patch("/api/agents/reddit/", {"enabled": False}, format="json").status_code == 200
    assert AgentConfig.for_project(project, "reddit").schedule["kind"] == "custom"

    # Replacing it clears the warning.
    data = client.patch("/api/agents/reddit/", {"schedule": {"kind": "every_hours", "hours": 1, "minute": 0}},
                        format="json").json()
    assert data["schedule_warning"] is None
    assert CrontabSchedule.objects.filter(minute="0", hour="*").exists()


def test_an_hourly_custom_schedule_is_not_flagged(client, project):
    config = AgentConfig.for_project(project, "reddit")
    config.schedule = {"kind": "custom", "cron": "0 9 1,15 * *"}
    config.save()
    assert client.get("/api/agents/reddit/").json()["schedule_warning"] is None


def test_min_gap():
    from datetime import timedelta

    from apps.agents.schedule import min_gap

    assert min_gap(parse_schedule({"kind": "every_hours", "hours": 4, "minute": 0}), "UTC") == timedelta(hours=4)
    assert min_gap(parse_schedule({"kind": "daily", "times": ["09:00", "17:00"]}), "UTC") == timedelta(hours=8)
