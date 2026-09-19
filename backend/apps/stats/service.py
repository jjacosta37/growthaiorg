"""Weekly stats: drafts per agent (generated, posted, dismissed), LLM and Apify spend, Reddit funnel."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncWeek
from django.utils import timezone

from apps.agents.models import ExternalUsage
from apps.inbox.models import Draft
from apps.reddit.models import RedditPost
from llm.models import LLMCall

AGENTS = ["reddit", "content", "x"]
# Which agent an LLM call's run belongs to, for spend attribution.
RUN_KIND_GROUP = {"reddit": "reddit", "content": "content", "x": "x", "onboarding": "context", "recrawl": "context",
                  "regenerate_doc": "context", "regenerate_draft": "regenerations"}


def week_starts(weeks: int, now: datetime | None = None) -> list[datetime]:
    now = now or timezone.now()
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return [this_monday - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]


def _series(rows, starts, key="week", value="n", cast=int) -> list:
    by_week = {r[key].date(): r[value] for r in rows}
    return [cast(by_week.get(s.date()) or 0) for s in starts]


def _usd(x) -> float:
    return float(Decimal(x or 0).quantize(Decimal("0.0001")))


def build_stats(project, weeks: int = 8) -> dict:
    starts = week_starts(weeks)
    since = starts[0]
    drafts = Draft.objects.filter(project=project)

    def weekly(qs, field):
        return (qs.filter(**{f"{field}__gte": since}).annotate(week=TruncWeek(field)).values("week")
                .annotate(n=Count("id")))

    per_agent = {}
    totals = {}
    reasons = {}
    for agent in AGENTS:
        qs = drafts.filter(agent_type=agent)
        generated = _series(weekly(qs, "created_at"), starts)
        posted = _series(weekly(qs.exclude(posted_at=None), "posted_at"), starts)
        dismissed = _series(weekly(qs.exclude(dismissed_at=None), "dismissed_at"), starts)
        per_agent[agent] = {"generated": generated, "posted": posted, "dismissed": dismissed}
        g, p, d = sum(generated), sum(posted), sum(dismissed)
        totals[agent] = {
            "generated": g, "posted": p, "dismissed": d,
            "pending": qs.filter(status=Draft.Status.NEW).count(),
            "post_rate": round(p / (p + d), 3) if p + d else None,  # of the drafts I acted on
        }
        reasons[agent] = dict(qs.filter(dismissed_at__gte=since).values_list("dismiss_reason")
                              .annotate(n=Count("id")).values_list("dismiss_reason", "n"))

    calls = LLMCall.objects.filter(project=project, created_at__gte=since)
    llm_weekly = _series(calls.annotate(week=TruncWeek("created_at")).values("week").annotate(n=Sum("cost_usd")),
                         starts, cast=_usd)
    by_group = defaultdict(Decimal)
    for kind, cost in calls.values_list("agent_run__kind").annotate(c=Sum("cost_usd")).values_list(
            "agent_run__kind", "c"):
        by_group[RUN_KIND_GROUP.get(kind, "other")] += cost or 0
    by_model = dict(calls.values_list("model").annotate(c=Sum("cost_usd")).values_list("model", "c"))
    tokens = calls.aggregate(inp=Sum("input_tokens"), cr=Sum("cache_read_tokens"), cw=Sum("cache_write_tokens"))
    prompt_tokens = sum(v or 0 for v in tokens.values())

    ext = ExternalUsage.objects.filter(project=project, created_at__gte=since)
    apify_weekly = _series(ext.annotate(week=TruncWeek("created_at")).values("week").annotate(n=Sum("cost_usd")),
                           starts, cast=_usd)
    by_purpose = dict(ext.values_list("purpose").annotate(c=Sum("cost_usd")).values_list("purpose", "c"))

    posts = RedditPost.objects.filter(project=project, fetched_at__gte=since)
    return {
        "weeks": [s.date().isoformat() for s in starts],
        "drafts": per_agent,
        "totals": totals,
        "dismiss_reasons": reasons,
        "spend": {
            "llm_weekly": llm_weekly,
            "apify_weekly": apify_weekly,
            "llm_total": round(sum(llm_weekly), 4),
            "apify_total": round(sum(apify_weekly), 4),
            "total": round(sum(llm_weekly) + sum(apify_weekly), 4),
            "llm_by_agent": {k: _usd(v) for k, v in sorted(by_group.items())},
            "llm_by_model": {k: _usd(v) for k, v in sorted(by_model.items())},
            "apify_by_purpose": {k: _usd(v) for k, v in sorted(by_purpose.items())},
            "llm_calls": calls.count(),
            "llm_failed_calls": calls.exclude(status=LLMCall.Status.OK).count(),
            "cache_hit_rate": round((tokens["cr"] or 0) / prompt_tokens, 3) if prompt_tokens else None,
        },
        "reddit": {
            "scanned": _series(posts.annotate(week=TruncWeek("fetched_at")).values("week").annotate(n=Count("id")),
                               starts),
            "drafted": per_agent["reddit"]["generated"],
        },
    }
