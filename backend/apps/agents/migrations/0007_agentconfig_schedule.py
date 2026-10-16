"""Replace AgentConfig.cron with a structured schedule.

Each saved cron becomes the builder schedule it expresses, or `custom` when it isn't one of the
builder's shapes, so every agent keeps firing at the same moments. Beat's PeriodicTask rows are
left as they are: projects have no timezone yet, which means UTC, exactly what they ran in.
"""

import apps.agents.models
from django.db import migrations, models


def crons_to_schedules(apps, schema_editor):
    from apps.agents.schedule import from_cron

    AgentConfig = apps.get_model("agents", "AgentConfig")
    for config in AgentConfig.objects.all():
        config.schedule = from_cron(config.cron)
        config.save(update_fields=["schedule"])


def schedules_to_crons(apps, schema_editor):
    from apps.agents.schedule import parse_schedule, to_entries

    AgentConfig = apps.get_model("agents", "AgentConfig")
    for config in AgentConfig.objects.all():
        first = to_entries(parse_schedule(config.schedule))[0]  # a reverse can only keep one entry
        config.cron = " ".join(first[k] for k in ("minute", "hour", "day_of_month", "month_of_year", "day_of_week"))
        config.save(update_fields=["cron"])


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0006_alter_agentconfig_publish_mode_alter_agentrun_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentconfig",
            name="schedule",
            field=models.JSONField(default=apps.agents.models.default_schedule),
        ),
        migrations.RunPython(crons_to_schedules, schedules_to_crons),
        migrations.RemoveField(model_name="agentconfig", name="cron"),
    ]
