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
