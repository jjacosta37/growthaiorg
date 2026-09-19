import json

import pytest

from apps.agents.models import AgentConfig, AgentRun
from apps.agents.runs import create_run
from apps.context import tasks
from apps.context.models import ContextDocument, CrawledPage
from apps.core.models import Project
from llm.models import LLMCall
from providers.crawl import CrawledPageData, CrawlResult
from tests.fakes import message, schema_title, task_system

pytestmark = pytest.mark.django_db

DOC_MARKERS = {
    "**Product Information** document": "# Product Information\nOpenWealth shows portfolio analytics.",
    "**Target Audience** document": "# Target Audience\nSelf-directed investors.",
    "**Brand Voice** document": "# Brand Voice\nClear and calm.",
    "**Competitor Analysis** document": "# Competitor Analysis\n### Acme (https://acme.example)",
    "**Content Strategy** document": "# Content Strategy\nPillars.",
}
FACTS = {"product_summary": "OpenWealth is portfolio analytics. For retail investors.",
         "competitors": [{"name": "Acme", "url": "https://acme.example"}, {"name": "Beta", "url": ""},
                         {"name": "Gamma", "url": "gamma.example"}]}
REDDIT = {"subreddits": [{"name": "r/Bogleheads", "reason": "index investors"},
                         {"name": "personalfinance", "reason": "questions"},
                         {"name": "Bogleheads", "reason": "dup"}],
          "keywords": ["portfolio tracker", " asset allocation ", "portfolio tracker", ""]}


IDENTITY = {"product_name": "Acme Wealth", "industry_pack": "financial_services", "reason": "portfolio analytics"}


def responder(fail=(), identity=None):
    def respond(params):
        title = schema_title(params)
        if title == "ProjectIdentity":
            return message(json.dumps(identity or IDENTITY))
        if title == "ProjectFacts":
            return message(json.dumps(FACTS))
        if title == "RedditSuggestions":
            return message(json.dumps(REDDIT))
        system = task_system(params)
        for marker, body in DOC_MARKERS.items():
            if marker in system:
                if marker in fail:
                    return message([], stop_reason="refusal")
                return message(body)
        raise AssertionError(f"unexpected request: {system[:80]}")

    return respond


def fake_crawl(n_pages):
    def crawl(url, max_pages, progress=None, delay_seconds=0, renderer=None):
        progress("Found pages")
        pages = [CrawledPageData(url=f"{url}/p{i}", title=f"P{i}", text=f"Page {i} text " * 50) for i in range(n_pages)]
        return CrawlResult(root_url=url, discovery="sitemap", discovered=n_pages, pages=pages,
                           skipped=[(f"{url}/x", "HTTP 404")])

    return crawl


@pytest.fixture
def project():
    p = Project.current()
    p.website_url = "https://ow.example"
    p.competitors = [{"name": "acme", "url": ""}]  # added by hand earlier; must not duplicate
    p.save()
    return p


def run_onboarding(project, kind=AgentRun.Kind.ONBOARDING, **params):
    run = create_run(project, kind, params=params)
    tasks.onboarding_task(run.id)
    run.refresh_from_db()
    return run


def test_full_onboarding(project, fake_anthropic, monkeypatch):
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    fake = fake_anthropic(responder=responder())

    run = run_onboarding(project)

    assert run.status == "succeeded", run.error or run.stats
    assert CrawledPage.objects.filter(project=project).count() == 5
    docs = {d.kind: d for d in ContextDocument.objects.filter(project=project)}
    assert set(docs) == {"product", "audience", "brand_voice", "competitors", "content_strategy", "compliance"}
    assert docs["product"].source == "ai" and docs["product"].prompt_version == "v1"
    assert docs["compliance"].source == "template" and docs["compliance"].prompt_version == "pack:financial_services"
    assert "Acme Wealth" in docs["compliance"].content_md and "No performance claims" in docs["compliance"].content_md
    assert docs["product"].revisions.count() == 1

    project.refresh_from_db()
    assert project.name == "Acme Wealth"  # identified from the site
    assert project.content_policy.pack == "financial_services" and project.content_policy.source == "suggested"
    assert project.onboarded_at is not None
    assert project.product_summary.startswith("OpenWealth is")
    assert project.competitors == [  # merged case-insensitively; bare domains get a scheme
        {"name": "acme", "url": ""}, {"name": "Beta", "url": ""}, {"name": "Gamma", "url": "https://gamma.example"}
    ]

    reddit = AgentConfig.objects.get(project=project, agent_type="reddit").config
    assert reddit == {"subreddits": ["Bogleheads", "personalfinance"],
                      "keywords": ["portfolio tracker", "asset allocation"]}

    # LLM calls: identify + 5 docs + facts + suggestions, all linked to the run.
    assert LLMCall.objects.filter(agent_run=run).count() == 8

    # The crawled site is in the cached prefix, identical across the five doc calls.
    doc_calls = [c for c in fake.messages.calls if schema_title(c) is None]
    # Docs are written under the suggested pack's rules, with the identified name.
    assert "`returns_claim`" in doc_calls[0]["system"][0]["text"]
    assert "for Acme Wealth" in doc_calls[0]["system"][-1]["text"]
    site_blocks = {c["system"][1]["text"] for c in doc_calls}
    assert len(site_blocks) == 1 and "<page url=\"https://ow.example/p0\"" in site_blocks.pop()
    assert all(c["system"][1]["cache_control"] == {"type": "ephemeral"} for c in doc_calls)
    # Later docs see earlier ones.
    last_user = doc_calls[-1]["messages"][0]["content"]
    assert '<document title="Product Information">' in last_user

    messages = list(run.events.values_list("message", flat=True))
    assert "Writing Product Information" in messages and "Context is ready" in messages


def test_competitor_research_uses_web_search(project, fake_anthropic, monkeypatch):
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    fake = fake_anthropic(responder=responder())
    run_onboarding(project)
    comp = next(c for c in fake.messages.calls if "**Competitor Analysis**" in task_system(c))
    assert comp["tools"][0]["name"] == "web_search"
    assert "acme" in comp["messages"][0]["content"]  # known competitors passed in


def test_doc_failure_makes_run_partial(project, fake_anthropic, monkeypatch):
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    fake_anthropic(responder=responder(fail={"**Brand Voice** document"}))

    run = run_onboarding(project)

    assert run.status == "partial"
    assert any("Brand Voice" in e for e in run.stats["errors"])
    assert not ContextDocument.objects.filter(project=project, kind="brand_voice").exists()
    assert ContextDocument.objects.filter(project=project, kind="content_strategy").exists()


def test_few_pages_warns_and_zero_pages_fails(project, fake_anthropic, monkeypatch):
    fake_anthropic(responder=responder())
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(2))
    run = run_onboarding(project)
    assert run.status == "succeeded"
    assert any("Only 2 readable page" in w for w in run.stats["warnings"])

    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(0))
    run = run_onboarding(project, AgentRun.Kind.RECRAWL)
    assert run.status == "failed" and "No readable pages" in run.error


def test_recrawl_keeps_human_edits_and_config(project, fake_anthropic, monkeypatch):
    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    fake_anthropic(responder=responder())
    run_onboarding(project)

    from apps.context.documents import save_document

    save_document(project, "brand_voice", "# Brand Voice\nMy edit.", source="human")
    cfg = AgentConfig.objects.get(project=project, agent_type="reddit")
    cfg.config = {"subreddits": ["investing"], "keywords": ["mine"]}
    cfg.save()

    run = run_onboarding(project, AgentRun.Kind.RECRAWL)

    assert run.status == "succeeded"
    voice = ContextDocument.objects.get(project=project, kind="brand_voice")
    assert voice.content_md.startswith("# Brand Voice\nMy edit")
    assert "Kept Brand Voice (edited by you)" in run.events.values_list("message", flat=True)
    cfg.refresh_from_db()
    assert cfg.config == {"subreddits": ["investing"], "keywords": ["mine"]}
    assert run.stats["reddit_suggestions"]["subreddits"] == ["Bogleheads", "personalfinance"]

    run = run_onboarding(project, AgentRun.Kind.RECRAWL, overwrite_edited=True)
    assert ContextDocument.objects.get(project=project, kind="brand_voice").source == "ai"


def test_site_block_budget_reports_overflow(project, settings):
    from apps.context.pipeline import render_site_block

    settings.CONTEXT_PAGE_CHAR_LIMIT = 100
    settings.CONTEXT_SITE_CHAR_BUDGET = 250
    pages = [CrawledPage(url=f"https://ow.example/{i}", title=str(i), content_text="x" * 500) for i in range(4)]
    text, left_out = render_site_block(project, pages)
    assert left_out == 2
    assert text.count("<page ") == 2 and "x" * 101 not in text


def test_config_error_fails_run_fast(project, fake_anthropic, monkeypatch):
    import anthropic
    import httpx2

    monkeypatch.setattr("apps.context.pipeline.crawl_site", fake_crawl(5))
    response = httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    fake = fake_anthropic(responder=lambda p: anthropic.AuthenticationError("bad", response=response, body=None))

    run = run_onboarding(project)

    assert run.status == "failed" and "credentials" in run.error
    assert len(fake.messages.calls) == 1  # stopped at the first doc instead of trying all five


def test_thin_pages_warn_and_rendering_is_costed(project, fake_anthropic, monkeypatch, settings):
    from decimal import Decimal

    from apps.agents.models import ExternalUsage
    from providers.crawl import RenderResult

    fake_anthropic(responder=responder())

    def crawl(url, max_pages, progress=None, delay_seconds=0, renderer=None):
        pages = [CrawledPageData(url=f"{url}/p{i}", title=f"P{i}", text="Real text " * 50) for i in range(4)]
        pages.append(CrawledPageData(url=f"{url}/pricing", title="Pricing", text="Pricing\nOne plan.", thin=True))
        result = CrawlResult(root_url=url, discovery="sitemap", discovered=5, pages=pages)
        if renderer is not None:
            result.render = RenderResult(provider="apify", external_id="r1", cost_usd=Decimal("0.04"))
        return result

    monkeypatch.setattr("apps.context.pipeline.crawl_site", crawl)

    settings.APIFY_TOKEN = ""
    run = run_onboarding(project)
    assert run.stats["pages_thin"] == 1
    assert any("only render with JavaScript" in w and "Set APIFY_TOKEN" in w for w in run.stats["warnings"])
    assert not ExternalUsage.objects.exists()

    settings.APIFY_TOKEN = "tok"
    run = run_onboarding(project, AgentRun.Kind.RECRAWL)
    usage = ExternalUsage.objects.get()
    assert (usage.provider, usage.purpose, usage.cost_usd, usage.agent_run_id) == ("apify", "render_pages",
                                                                                   Decimal("0.04"), run.id)
