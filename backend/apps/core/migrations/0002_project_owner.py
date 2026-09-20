"""Give every project an owner.

Added nullable, backfilled, then made required, so an existing database migrates without
losing its project.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assign_owner(apps, schema_editor):
    """Attach existing projects to the admin user.

    Before this migration nothing linked users to projects, so the only sensible owner is
    the single admin the installation already had. A project with no user to own it can
    only be the auto-created empty default, so it is dropped rather than blocking the
    migration.
    """
    Project = apps.get_model("core", "Project")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    orphans = Project.objects.filter(owner__isnull=True)
    if not orphans.exists():
        return

    owner = User.objects.filter(is_superuser=True).order_by("pk").first()
    if owner is None:
        owner = User.objects.order_by("pk").first()

    if owner is None:
        orphans.delete()
    else:
        orphans.update(owner=owner)


def unassign_owner(apps, schema_editor):
    """Reverse is a no-op: dropping the column discards the link anyway."""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(assign_owner, unassign_owner),
        migrations.AlterField(
            model_name="project",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="project",
            index=models.Index(fields=["owner", "id"], name="core_projec_owner_i_9e7394_idx"),
        ),
    ]
