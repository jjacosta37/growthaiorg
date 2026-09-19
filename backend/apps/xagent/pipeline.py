"""X Agent: plan varied formats, draft single posts and short threads in one call, keep them
within X's limits, and avoid repeating recent drafts."""

import llm
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter
from apps.core.text import is_near_duplicate
from apps.inbox import compliance, services
from apps.inbox.models import Draft, DraftKind, DraftVersion
from apps.inbox.nudges import nudge_instruction
from apps.policy.service import policy_for

from .config import FORMATS, XAgentConfig
from .length import x_length

X_KINDS = (DraftKind.X_POST, DraftKind.X_THREAD)


def load_config(project) -> XAgentConfig:
    return XAgentConfig.model_validate(AgentConfig.for_project(project, AgentType.X).config)


def recent_items(project, limit: int) -> list[dict]:
    """Newest first: {format, angle, text} of recent X drafts (any status)."""
    drafts = (Draft.objects.filter(project=project, kind__in=X_KINDS).select_related("current_version")
              .order_by("-created_at")[:limit])
    out = []
    for d in drafts:
        c = d.current_version.content if d.current_version else {}
        out.append({"format": c.get("format", ""), "angle": c.get("angle", ""), "text": " / ".join(c.get("posts", []))})
    return out


def plan_formats(cfg: XAgentConfig, recent: list[dict]) -> list[str]:
    """Least recently used formats first (never-used first), cycling if more posts than formats."""
    last_used = {}
    for i, item in enumerate(recent):  # newest first
        last_used.setdefault(item["format"], i)
    never = len(recent) + 1
    order = sorted(cfg.formats, key=lambda f: (-last_used.get(f, never), cfg.formats.index(f)))
    return [order[i % len(order)] for i in range(cfg.posts_per_run)]


def over_limit(posts: list[str], limit: int) -> list[tuple[int, int]]:
    """(index, length) of posts over the limit."""
    return [(i, n) for i, p in enumerate(posts) if (n := x_length(p)) > limit]


def length_flags(posts: list[str], limit: int) -> list[dict]:
    return [{"rule": "length", "excerpt": posts[i][:60] + "…",
             "explanation": f"Post {i + 1} is {n} characters; the limit is {limit}."}
            for i, n in over_limit(posts, limit)]


def clean_posts(posts: list[str], max_posts: int) -> list[str]:
    return [p.strip() for p in posts if p.strip()][:max_posts]


def revise(project, run, item: dict, cfg: XAgentConfig, instruction: str):
    variables = {
        "project_name": project.name, "format": item["format"], "format_description": FORMATS.get(item["format"], ""),
        "angle": item["angle"], "posts": item["posts"], "char_limit": cfg.char_limit,
        "max_thread_posts": cfg.max_thread_posts, "instruction": instruction,
        "lengths": [x_length(p) for p in item["posts"]],
    }
    return llm.complete("x.revise", variables, project=project, run=run)


def save_draft(run, item: dict, result, cfg: XAgentConfig) -> Draft:
    kind = DraftKind.X_THREAD if len(item["posts"]) > 1 else DraftKind.X_POST
    draft = services.create_draft(run.project, agent_type=AgentType.X, kind=kind, content=item, result=result,
                                  run=run)
    compliance.lint(draft, run)
    if extra := length_flags(item["posts"], cfg.char_limit):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    return draft


def run_x_agent(run: AgentRun, reporter: RunReporter) -> None:
    project = run.project
    cfg = load_config(project)
    recent = recent_items(project, cfg.recent_window)
    formats = plan_formats(cfg, recent)
    reporter.step(f"Drafting {len(formats)} X post(s): {', '.join(formats)}")
    result = llm.complete("x.posts", {
        "project_name": project.name, "author_role": policy_for(project).author_role,
        "plan": [{"id": f, "description": FORMATS[f]} for f in formats],
        "char_limit": cfg.char_limit, "max_thread_posts": cfg.max_thread_posts, "recent": recent,
        "guidance": cfg.guidance,
    }, project=project, run=run)

    seen = [r["text"] for r in recent]
    stats = {"planned": len(formats), "drafted": 0, "duplicates": 0, "revised": 0, "over_limit": 0}
    for raw in result.parsed.items:
        item = {"format": raw.format if raw.format in FORMATS else "", "angle": raw.angle.strip(),
                "posts": clean_posts(raw.posts, cfg.max_thread_posts)}
        if not item["posts"]:
            continue
        if is_near_duplicate(" ".join(item["posts"]), seen, threshold=0.5):
            stats["duplicates"] += 1
            continue
        item_result = result
        if over := over_limit(item["posts"], cfg.char_limit):
            stats["revised"] += 1
            too_long = ", ".join(f"post {i + 1} is {n}" for i, n in over)
            try:
                item_result = revise(project, run, item, cfg,
                                     f"Shorten to fit the {cfg.char_limit}-character limit ({too_long}). "
                                     "Keep the idea; cut words, not substance.")
                item = {**item, "posts": clean_posts(item_result.parsed.posts, cfg.max_thread_posts) or item["posts"]}
            except llm.LLMError as exc:
                reporter.error(f"Couldn't shorten a post: {exc}")
                item_result = result
            if over_limit(item["posts"], cfg.char_limit):
                stats["over_limit"] += 1
        save_draft(run, item, item_result, cfg)
        seen.append(" / ".join(item["posts"]))
        stats["drafted"] += 1

    run.stats.update(stats)
    run.save(update_fields=["stats"])
    extras = [f"{stats['duplicates']} too similar to recent posts" if stats["duplicates"] else "",
              f"{stats['over_limit']} still over the limit (flagged)" if stats["over_limit"] else ""]
    reporter.success(f"Drafted {stats['drafted']} X post(s)" + "".join(f"; {e}" for e in extras if e))


def regenerate(draft: Draft, nudge: str, instruction: str, run) -> DraftVersion:
    cfg = load_config(draft.project)
    content = draft.current_version.content
    item = {"format": content.get("format", ""), "angle": content.get("angle", ""), "posts": content["posts"]}
    text = nudge_instruction(nudge, instruction, draft.project.name) or "Write a fresh, better version."
    result = revise(draft.project, run, item, cfg, text)
    posts = clean_posts(result.parsed.posts, cfg.max_thread_posts) or item["posts"]
    version = services.add_version(draft, {**item, "posts": posts}, source=DraftVersion.Source.AI_REGENERATED,
                                   result=result, nudge=nudge, instruction=instruction)
    compliance.lint(draft, run)
    if extra := length_flags(posts, cfg.char_limit):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    return version
