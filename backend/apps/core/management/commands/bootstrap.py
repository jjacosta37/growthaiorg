"""Idempotent setup for fresh environments: the single admin user and the default project."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.core.models import Project
from config.settings.base import env


class Command(BaseCommand):
    help = "Create the admin user (from HELMLY_ADMIN_* env vars) and the default project."

    def handle(self, *args, **options):
        username = env("HELMLY_ADMIN_USERNAME", default="")
        password = env("HELMLY_ADMIN_PASSWORD", default="")
        email = env("HELMLY_ADMIN_EMAIL", default="")
        User = get_user_model()
        if not (username and password):
            self.stdout.write("HELMLY_ADMIN_USERNAME/HELMLY_ADMIN_PASSWORD not set; skipping admin user")
        elif not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(f"Created admin user {username}")

        # The one place a project is created without a user asking for it. It runs
        # single-threaded in the one-shot `migrate` service, before web/worker/beat start,
        # so there is no second process to race with.
        owner = User.objects.filter(username=username).first() if username else None
        if owner is None:
            self.stdout.write("No admin user; skipping the default project")
            return
        project = owner.projects.first()
        if project is None:
            project = Project.objects.create(owner=owner, name=Project.DEFAULT_NAME)
            self.stdout.write(f"Created project {project.name!r} for {owner.username}")
        else:
            self.stdout.write(f"Project: {project.name}")
