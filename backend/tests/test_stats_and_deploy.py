from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agents.models import AgentRun, ExternalUsage
from apps.core.models import Project
from apps.inbox import services
from apps.inbox.models import Draft
from apps.stats.service import week_starts
from llm.models import LLMCall

pytestmark = pytest.mark.django_db


def make_draft(project, agent="reddit", kind="reddit_comment", content=None, created=None):
    d = Draft.objects.create(project=project, agent_type=agent, kind=kind)
    services.add_version(d, content or {"body": "hi"}, source="ai_initial")
    if created:
        Draft.objects.filter(pk=d.pk).update(created_at=created)
        d.refresh_from_db()
    return d


def test_week_starts_are_mondays():
    starts = week_starts(3)
    assert len(starts) == 3 and all(s.weekday() == 0 and s.hour == 0 for s in starts)
    assert starts[2] - starts[1] == timedelta(weeks=1)


def test_dismissed_at_set_and_cleared(project):
    d = make_draft(project)
    services.dismiss(d, "not_relevant")
    assert d.dismissed_at is not None
    services.restore(d)
    d.refresh_from_db()
    assert d.dismissed_at is None and d.status == "new"


def test_stats_weekly_counts_spend_and_rates(client, project):
    now = timezone.now()
    old = now - timedelta(weeks=1)
    # reddit: 3 generated (1 last week), 1 posted, 1 dismissed; x: 1 pending
    a = make_draft(project, created=old)
    b = make_draft(project)
    make_draft(project)
    services.mark_posted(a)
    services.dismiss(b, "too_promotional")
    make_draft(project, agent="x", kind="x_post", content={"posts": ["hello"]})
    # a draft outside the window doesn't count
    make_draft(project, created=now - timedelta(weeks=20))

    run = AgentRun.objects.create(project=project, kind="reddit", status="succeeded")
    ctx = AgentRun.objects.create(project=project, kind="onboarding", status="succeeded")
    LLMCall.objects.create(project=project, agent_run=run, task="reddit.score", model="claude-haiku-4-5-20251001",
                           prompt_version="v4", prompt_hash="h", cost_usd=Decimal("0.25"), input_tokens=100,
                           cache_read_tokens=300)
    LLMCall.objects.create(project=project, agent_run=ctx, task="context.product", model="claude-sonnet-5",
                           prompt_version="v1", prompt_hash="h", cost_usd=Decimal("0.50"), cache_write_tokens=100,
                           status="error")
    ExternalUsage.objects.create(project=project, provider="apify", purpose="reddit_search", cost_usd=Decimal("0.02"))

    data = client.get("/api/stats/?weeks=4").json()

    assert len(data["weeks"]) == 4
    reddit = data["drafts"]["reddit"]
    assert sum(reddit["generated"]) == 3 and reddit["generated"][-2:] == [1, 2]
    assert sum(reddit["posted"]) == 1 and sum(reddit["dismissed"]) == 1
    # pending = waiting in the inbox now, whatever its age (includes the 20-week-old draft)
    assert data["totals"]["reddit"] == {"generated": 3, "posted": 1, "dismissed": 1, "pending": 2, "post_rate": 0.5}
    assert data["totals"]["x"]["pending"] == 1 and data["totals"]["x"]["post_rate"] is None
    assert data["dismiss_reasons"]["reddit"] == {"too_promotional": 1}

    spend = data["spend"]
    assert (spend["llm_total"], spend["apify_total"], spend["total"]) == (0.75, 0.02, 0.77)
    assert spend["llm_by_agent"] == {"context": 0.5, "reddit": 0.25}
    assert spend["llm_by_model"] == {"claude-haiku-4-5-20251001": 0.25, "claude-sonnet-5": 0.5}
    assert spend["apify_by_purpose"] == {"reddit_search": 0.02}
    assert (spend["llm_calls"], spend["llm_failed_calls"]) == (2, 1)
    assert spend["cache_hit_rate"] == 0.6  # 300 read / (100 + 300 + 100)
    assert data["reddit"]["drafted"] == reddit["generated"]


def test_stats_empty_and_bad_params(client):
    data = client.get("/api/stats/?weeks=abc").json()
    assert len(data["weeks"]) == 8 and data["spend"]["cache_hit_rate"] is None
    assert len(client.get("/api/stats/?weeks=999").json()["weeks"]) == 52


def test_health_is_public():
    resp = APIClient().get("/api/health/")
    assert resp.status_code == 200 and resp.json() == {"ok": True}


def test_openapi_schema_generates_cleanly():
    """The frontend's TypeScript types are generated from this schema; keep it warning-free."""
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.generators import SchemaGenerator

    GENERATOR_STATS.reset()
    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert "/api/drafts/{id}/" in schema["paths"] and "/api/stats/" in schema["paths"]
    components = schema["components"]["schemas"]
    assert {"DraftStatusEnum", "RunStatusEnum", "DocKindEnum"} <= set(components)
    assert not [n for n in components if any(ch.isdigit() for ch in n)], "unnamed enum collisions"
    assert GENERATOR_STATS._warn_cache == {} and GENERATOR_STATS._error_cache == {}
