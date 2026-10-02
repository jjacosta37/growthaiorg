import logging

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create_user("me", password="pw")


def test_endpoints_require_login():
    client = APIClient()
    for url in ["/api/auth/me/", "/api/project/", "/api/status/"]:
        assert client.get(url).status_code == 403


def test_session_login_flow_with_csrf(user):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]

    bad = client.post("/api/auth/login/", {"username": "me", "password": "wrong"}, HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400

    ok = client.post("/api/auth/login/", {"username": "me", "password": "pw"}, HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and ok.json()["username"] == "me"
    assert client.get("/api/auth/me/").json()["username"] == "me"

    # Login rotates the CSRF token; unsafe requests need the fresh one.
    token = client.cookies["csrftoken"].value
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert client.get("/api/auth/me/").status_code == 403


def test_project_get_and_patch_competitors(client, project):
    data = client.get("/api/project/").json()
    assert data["name"] == project.name

    resp = client.patch(
        "/api/project/",
        {"website_url": "https://acme.example", "competitors": [{"name": "Globex", "url": "https://globex.example"}]},
        format="json",
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["competitors"] == [{"name": "Globex", "url": "https://globex.example"}]


@pytest.fixture
def anon():
    # The throttle counts in the default cache, which outlives a single test.
    from django.core.cache import cache

    cache.clear()
    return APIClient(enforce_csrf_checks=True)


def test_waitlist_signup_is_public_and_needs_no_csrf(anon):
    from apps.core.models import WaitlistSignup

    resp = anon.post("/api/waitlist/", {"email": " Founder@Example.com ", "source": "hero"}, format="json")
    assert resp.status_code == 201
    signup = WaitlistSignup.objects.get()
    assert (signup.email, signup.source) == ("founder@example.com", "hero")


def test_waitlist_repeat_email_looks_the_same(anon):
    from apps.core.models import WaitlistSignup

    for _ in range(2):
        assert anon.post("/api/waitlist/", {"email": "a@example.com"}, format="json").status_code == 201
    assert WaitlistSignup.objects.count() == 1


def test_waitlist_rejects_bad_email(anon):
    resp = anon.post("/api/waitlist/", {"email": "not-an-email"}, format="json")
    assert resp.status_code == 400


def test_waitlist_logs_the_id_not_the_email(anon, caplog):
    caplog.set_level(logging.INFO, logger="apps.core.views")
    anon.post("/api/waitlist/", {"email": "private@example.com", "source": "cta"}, format="json")
    assert "waitlist signup" in caplog.text
    assert "private@example.com" not in caplog.text


def test_waitlist_is_throttled(anon):
    codes = [
        anon.post("/api/waitlist/", {"email": f"u{i}@example.com"}, format="json").status_code
        for i in range(11)
    ]
    assert codes[:10] == [201] * 10 and codes[10] == 429


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest", "http://10.0.0.5", "http://printer.local"])
def test_project_website_url_must_be_public(client, project, url):
    assert client.patch("/api/project/", {"website_url": url}, format="json").status_code == 400
    assert client.post("/api/projects/", {"name": "Fresh", "website_url": url}, format="json").status_code == 400
    # Blank stays allowed: a project can exist before its site is known.
    assert client.patch("/api/project/", {"website_url": ""}, format="json").status_code == 200
