"""The "Suggest more" action: new subreddits and keywords for the Reddit Agent, learned from its own history.

One model call per click, no tools and no provider calls (docs/prds/0004-reddit-target-suggestions.md).
The model sees the context docs, the current targets with how each one performed over the last
`HISTORY_DAYS`, and what the user dismissed before. What it proposes is stored as pending
`RedditTargetSuggestion` rows; nothing reaches the config until a person adds it.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone

import llm
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter

from .config import MAX_KEYWORD_CHARS, SUBREDDIT_NAME, RedditAgentConfig
from .models import RedditPost, RedditTargetSuggestion

HISTORY_DAYS = 30
MAX_SUGGESTED_SUBREDDITS = 10
MAX_SUGGESTED_KEYWORDS = 15
DISMISSED_SHOWN = 200  # the newest dismissals passed to the model; older ones are still filtered
REASON_CHARS = 300

Kind = RedditTargetSuggestion.Kind


def normalise(kind: str, raw: str) -> str:
    """The value as the config would save it: subreddits without `r/` or slashes, keywords with single spaces."""
    if kind == Kind.SUBREDDIT:
        return raw.strip().removeprefix("r/").strip("/").strip()
    return " ".join(raw.split())


def valid(kind: str, value: str) -> bool:
    """Whether the config would accept `value` if the user typed it (`RedditAgentConfig`'s rules)."""
    if kind == Kind.SUBREDDIT:
        return bool(SUBREDDIT_NAME.match(value))
    return bool(value) and len(value) <= MAX_KEYWORD_CHARS


def config_keys(cfg: RedditAgentConfig) -> dict[str, set[str]]:
    """The lowercased subreddits and keywords already in the config, per kind."""
    return {
        Kind.SUBREDDIT: {normalise(Kind.SUBREDDIT, s).lower() for s in cfg.subreddits},
        Kind.KEYWORD: {normalise(Kind.KEYWORD, k).lower() for k in cfg.keywords},
    }


def reddit_config(project) -> tuple[AgentConfig, RedditAgentConfig]:
    """The Reddit Agent's config row and its validated settings."""
    config = AgentConfig.for_project(project, AgentType.REDDIT)
    return config, RedditAgentConfig.model_validate(config.config)


def target_history(project, cfg: RedditAgentConfig, days: int = HISTORY_DAYS) -> dict:
    """How each current subreddit and keyword performed over the last `days`.

    Every current target is listed, including those that found nothing: that is the signal the
    model most needs. Per subreddit, `returned` counts search results (repeats included) from the
    runs' saved `by_subreddit`; runs from before that was saved count as 0. `new` and `drafted`
    count posts first seen in the window. Per keyword, `mentions` and `drafted` count the window's
    posts that contain it, which stands in for "found by it": a run searches all keywords at once.
    """
    since = timezone.now() - timedelta(days=days)
    subs = [normalise(Kind.SUBREDDIT, s) for s in cfg.subreddits]
    returned = dict.fromkeys((s.lower() for s in subs), 0)
    runs = AgentRun.objects.filter(project=project, kind__in=[AgentRun.Kind.REDDIT, AgentRun.Kind.CONTENT],
                                   created_at__gte=since).values_list("stats", flat=True)
    for stats in runs:
        for name, n in ((stats or {}).get("by_subreddit") or {}).items():
            key = normalise(Kind.SUBREDDIT, name).lower()
            if key in returned and isinstance(n, int):
                returned[key] += n

    posts = RedditPost.objects.filter(project=project, fetched_at__gte=since)
    per_sub = {
        row["sub"]: row
        for row in posts.annotate(sub=Lower("subreddit")).values("sub")
        .annotate(new=Count("id", distinct=True), drafted=Count("id", filter=Q(drafts__isnull=False), distinct=True))
    }
    keywords = [normalise(Kind.KEYWORD, k) for k in cfg.keywords]
    aggregates = {}
    for i, kw in enumerate(keywords):
        mentions = Q(title__icontains=kw) | Q(body__icontains=kw)
        aggregates[f"m{i}"] = Count("id", filter=mentions, distinct=True)
        aggregates[f"d{i}"] = Count("id", filter=mentions & Q(drafts__isnull=False), distinct=True)
    counts = posts.aggregate(**aggregates) if aggregates else {}
    return {
        "days": days,
        "subreddits": [
            {"name": s, "returned": returned[s.lower()], "new": per_sub.get(s.lower(), {}).get("new", 0),
             "drafted": per_sub.get(s.lower(), {}).get("drafted", 0)}
            for s in subs
        ],
        "keywords": [
            {"term": kw, "mentions": counts.get(f"m{i}") or 0, "drafted": counts.get(f"d{i}") or 0}
            for i, kw in enumerate(keywords)
        ],
    }


def run_suggest_targets(run: AgentRun, reporter: RunReporter) -> None:
    """Ask the model for new subreddits and keywords and store the usable ones as pending suggestions.

    The previous pending suggestions are replaced only once this succeeds, so a failed call
    leaves both them and the config as they were.

    Raises:
        llm.LLMError: The model call failed; `running()` marks the run failed.
    """
    project = run.project
    _, cfg = reddit_config(project)
    history = target_history(project, cfg)
    dismissed_rows = RedditTargetSuggestion.objects.filter(project=project,
                                                           status=RedditTargetSuggestion.Status.DISMISSED)
    dismissed = {kind: set() for kind in Kind.values}
    for kind, key in dismissed_rows.values_list("kind", "key"):
        dismissed[kind].add(key)
    shown = list(dismissed_rows.order_by("-decided_at", "-id").values("kind", "value")[:DISMISSED_SHOWN])

    reporter.step("Suggesting more subreddits and keywords", subreddits=len(cfg.subreddits),
                  keywords=len(cfg.keywords), dismissed=len(shown), history_days=history["days"])
    result = llm.complete(
        "reddit.target_suggestions",
        {
            "history": history,
            "dismissed_subreddits": [d["value"] for d in shown if d["kind"] == Kind.SUBREDDIT],
            "dismissed_keywords": [d["value"] for d in shown if d["kind"] == Kind.KEYWORD],
        },
        project=project,
        run=run,
    )
    proposed = [(Kind.SUBREDDIT, s.name, s.reason) for s in result.parsed.subreddits]
    proposed += [(Kind.KEYWORD, k.term, k.reason) for k in result.parsed.keywords]

    # Model output: keep only what the config would accept if the user typed it, and nothing the
    # user already has or turned down (docs/security-patterns.md §7).
    existing = config_keys(cfg)
    caps = {Kind.SUBREDDIT: MAX_SUGGESTED_SUBREDDITS, Kind.KEYWORD: MAX_SUGGESTED_KEYWORDS}
    kept: dict[str, dict[str, RedditTargetSuggestion]] = {kind: {} for kind in Kind.values}
    dropped = {"invalid": 0, "existing": 0, "dismissed": 0, "over_cap": 0}
    for kind, raw, reason in proposed:
        value = normalise(kind, raw)
        key = value.lower()
        if not valid(kind, value):
            dropped["invalid"] += 1
        elif key in existing[kind]:
            dropped["existing"] += 1
        elif key in dismissed[kind]:
            dropped["dismissed"] += 1
        elif key in kept[kind]:
            continue  # the model repeated itself
        elif len(kept[kind]) >= caps[kind]:
            dropped["over_cap"] += 1
        else:
            kept[kind][key] = RedditTargetSuggestion(project=project, run=run, kind=kind, value=value, key=key,
                                                     reason=" ".join(reason.split())[:REASON_CHARS])

    rows = [*kept[Kind.SUBREDDIT].values(), *kept[Kind.KEYWORD].values()]
    with transaction.atomic():
        RedditTargetSuggestion.objects.filter(project=project, status=RedditTargetSuggestion.Status.PENDING).delete()
        RedditTargetSuggestion.objects.bulk_create(rows)
    run.stats.update(suggested=len(rows), suggested_subreddits=len(kept[Kind.SUBREDDIT]),
                     suggested_keywords=len(kept[Kind.KEYWORD]), dropped=dropped)
    run.save(update_fields=["stats"])
    if rows:
        reporter.success(f"Suggested {len(kept[Kind.SUBREDDIT])} subreddits and {len(kept[Kind.KEYWORD])} keywords",
                         subreddits=list(kept[Kind.SUBREDDIT]), keywords=list(kept[Kind.KEYWORD]), dropped=dropped)
    else:
        reporter.success("No new subreddits or keywords to suggest", dropped=dropped)


def pending_suggestions(project, cfg: RedditAgentConfig) -> list[RedditTargetSuggestion]:
    """Pending suggestions that aren't in the config, oldest first.

    A value the user typed into the config since the suggestion was made drops out here.
    """
    existing = config_keys(cfg)
    rows = RedditTargetSuggestion.objects.filter(project=project, status=RedditTargetSuggestion.Status.PENDING)
    return [r for r in rows if r.key not in existing[r.kind]]


class SuggestionLimit(ValueError):
    """Adding the chosen suggestions would take the config over a limit."""


def add_suggestions(project, ids: list[int]) -> int:
    """Append the chosen pending suggestions to the Reddit Agent's config and mark them added.

    Only the caller's project's pending rows are used; other ids are ignored. Nothing else in the
    config changes. Values already in the config are marked added without being repeated.

    Returns:
        How many values were appended to the config.

    Raises:
        SuggestionLimit: The result would exceed the config's subreddit or keyword limit; nothing changed.
    """
    with transaction.atomic():
        config = AgentConfig.objects.select_for_update().get(pk=reddit_config(project)[0].pk)
        cfg = RedditAgentConfig.model_validate(config.config)
        rows = list(RedditTargetSuggestion.objects.select_for_update().filter(
            project=project, status=RedditTargetSuggestion.Status.PENDING, pk__in=ids))
        existing = config_keys(cfg)
        additions = {kind: [] for kind in Kind.values}
        for row in rows:
            if row.key not in existing[row.kind]:
                existing[row.kind].add(row.key)
                additions[row.kind].append(row.value)
        try:
            merged = RedditAgentConfig.model_validate({
                **config.config,
                "subreddits": [*cfg.subreddits, *additions[Kind.SUBREDDIT]],
                "keywords": [*cfg.keywords, *additions[Kind.KEYWORD]],
            })
        except ValueError as exc:
            raise SuggestionLimit(_limit_message(exc)) from exc
        config.config = merged.model_dump()
        config.save(update_fields=["config", "updated_at"])
        RedditTargetSuggestion.objects.filter(pk__in=[r.pk for r in rows]).update(
            status=RedditTargetSuggestion.Status.ADDED, decided_at=timezone.now())
    return sum(len(v) for v in additions.values())


def _limit_message(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(str(e.get("msg", "")).removeprefix("Value error, ") for e in errors()) or str(exc)
    return str(exc)
