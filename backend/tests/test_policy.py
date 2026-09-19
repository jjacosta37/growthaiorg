import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.context.documents import save_document
from apps.context.models import ContextDocument
from apps.core.models import Project
from apps.policy.packs import get_pack
from apps.policy.service import policy_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(get_user_model().objects.create_user("me", password="pw"))
    return c


def test_packs_extend_general():
    general = {r["id"] for r in get_pack("general").rules}
    fin = {r["id"] for r in get_pack("financial_services").rules}
    health = get_pack("health_wellness")
    assert general < fin and {"returns_claim", "personalized_advice"} <= fin
    assert general < {r["id"] for r in health.rules} and "medical advice" in health.blog_disclaimer
    assert get_pack("general").blog_disclaimer == ""
    assert "Phrases to avoid" in get_pack("financial_services").compliance_doc  # extra appended


def test_default_policy_is_general(client):
    data = client.get("/api/policy/").json()
    assert (data["pack"], data["source"], data["author_role"]) == ("general", "default", "founder")
    assert data["disclosure_preview"] == "(Disclosure: I'm the founder of My project.)"
    assert {p["id"] for p in client.get("/api/policy/packs/").json()} >= {"general", "financial_services",
                                                                         "health_wellness"}


def test_apply_pack_and_edit_rules_resyncs_compliance_doc(client):
    project = Project.current()
    save_document(project, "compliance", "# old", source="template")

    resp = client.post("/api/policy/apply-pack/", {"pack": "financial_services"})
    assert resp.status_code == 200 and resp.json()["source"] == "user"
    doc = ContextDocument.objects.get(kind="compliance")
    assert "No performance claims" in doc.content_md and doc.prompt_version == "pack:financial_services"

    rules = resp.json()["rules"] + [{"id": "no_emoji", "title": "No emoji", "description": "Never use emoji."}]
    resp = client.patch("/api/policy/", {"rules": rules, "author_role": "CEO"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["disclosure_preview"] == "(Disclosure: I'm the CEO of My project.)"
    assert "Never use emoji." in ContextDocument.objects.get(kind="compliance").content_md

    save_document(project, "compliance", "# my own words", source="human")
    client.patch("/api/policy/", {"author_role": "founder"}, format="json")
    assert ContextDocument.objects.get(kind="compliance").content_md.startswith("# my own words")


def test_validation(client):
    assert client.post("/api/policy/apply-pack/", {"pack": "nope"}).status_code == 400
    bad = [{"id": "Bad Id", "title": "x", "description": "y"}]
    assert client.patch("/api/policy/", {"rules": bad}, format="json").status_code == 400
    dup = [{"id": "a", "title": "x", "description": "y"}, {"id": "a", "title": "x", "description": "y"}]
    assert client.patch("/api/policy/", {"rules": dup}, format="json").status_code == 400


def test_guardrails_follow_the_policy(fake_anthropic, prompts_tmp):
    import llm
    from tests.conftest import write_prompt
    from tests.fakes import message

    write_prompt(prompts_tmp, "t.x", "v1", "model_tier: fast\nschema: SmokeResult", "Do.", "Go")
    project = Project.current()
    project.name = "Glow"
    project.save()
    from apps.policy.service import apply_pack

    apply_pack(policy_for(project), "health_wellness", source="user")
    fake = fake_anthropic(message('{"ok": true, "echo": "x"}'))
    llm.complete("t.x", project=project)
    guardrails = fake.messages.calls[0]["system"][0]["text"]
    assert "drafting content for Glow" in guardrails
    assert "`medical_claims`" in guardrails and "`returns_claim`" not in guardrails
    assert "not medical advice" in guardrails


def test_user_policy_is_not_overwritten_by_onboarding(fake_anthropic, monkeypatch):
    from tests.test_onboarding import fake_crawl, responder, run_onboarding

    project = Project.current()
    project.website_url = "https://acme.example"
    project.name = "Chosen Name"
    project.save()
    from apps.policy.service import apply_pack

    apply_pack(policy_for(project), "general", source="user")
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    fake = fake_anthropic(responder=responder())

    run_onboarding(project)

    project.refresh_from_db()
    assert project.name == "Chosen Name" and project.content_policy.pack == "general"
    assert not any("ProjectIdentity" in str(c.get("output_config")) for c in fake.messages.calls)


def test_removing_disclosure_rule_drops_the_instruction():
    from apps.policy.service import guardrail_variables

    project = Project.current()
    policy = policy_for(project)
    assert guardrail_variables(project)["disclosure"] == "(Disclosure: I'm the founder of My project.)"
    policy.rules = [r for r in policy.rules if r["id"] != "missing_disclosure"]
    policy.save()
    assert guardrail_variables(project)["disclosure"] == ""
