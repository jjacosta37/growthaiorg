"""Idempotent setup for fresh environments: the admin account.

Projects are not created here — their owner names them on first sign-in."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from config.settings.base import env


class Command(BaseCommand):
    help = "Create the admin user from HELMLY_ADMIN_* env vars."

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

        # No project is created here. Projects belong to whoever owns them and are named
        # by that person, so the app asks on first sign-in rather than inventing one
        # called "My project". This command provisions the account, nothing more.
        owner = User.objects.filter(username=username).first() if username else None
        if owner is not None:
            self.stdout.write(f"{owner.username}: {owner.projects.count()} project(s)")
