"""Replace exception text stored before runs showed only public messages (security-patterns.md §10).

`AgentRun.error` held the full traceback and the "Failed: ..." event the raw exception, both
read by the UI. The text is already in the logs and Sentry, so nothing is lost here.
"""

from django.db import migrations

# A copy, not an import: a migration must not change when app code does.
GENERIC_FAILURE = "Something went wrong on Luka's side. It has been reported."


def scrub(apps, schema_editor):
    AgentRun = apps.get_model("agents", "AgentRun")
    RunEvent = apps.get_model("agents", "RunEvent")
    RedditPost = apps.get_model("reddit", "RedditPost")
    AgentRun.objects.exclude(error="").update(error=GENERIC_FAILURE)
    RunEvent.objects.filter(message__startswith="Failed: ").update(message=f"Failed: {GENERIC_FAILURE}")
    RedditPost.objects.exclude(score_error="").update(score_error=GENERIC_FAILURE)


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0008_suggest_reddit_targets"),
        ("reddit", "0003_suggest_reddit_targets"),
    ]

    operations = [
        migrations.RunPython(scrub, migrations.RunPython.noop),
    ]
