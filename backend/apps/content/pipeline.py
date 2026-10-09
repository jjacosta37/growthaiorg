"""Content Agent: keep a backlog of blog topics, and draft full SEO posts from it."""

import re

import llm
from apps.agents.draft_models import draft_model_for
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter
from apps.context.models import CrawledPage
from apps.core.text import is_near_duplicate, slugify
from apps.inbox import compliance, services
from apps.inbox.models import Draft, DraftKind, DraftVersion
from apps.inbox.nudges import nudge_instruction
from apps.policy.service import policy_for

from .config import ContentAgentConfig
from .models import BlogTopic

META_LIMIT = 160


def load_config(project) -> ContentAgentConfig:
    return ContentAgentConfig.model_validate(AgentConfig.for_project(project, AgentType.CONTENT).config)


def covered_titles(project) -> list[str]:
    """Everything already written or queued: published posts on the site, topics, and blog drafts."""
    titles = [t for t in BlogTopic.objects.filter(project=project).exclude(status=BlogTopic.Status.REJECTED)
              .values_list("title", flat=True)]
    for page in CrawledPage.objects.filter(project=project, url__contains="/blog/"):
        titles.append(page.title or page.url.rsplit("/", 1)[-1].replace("-", " "))
    for draft in Draft.objects.filter(project=project, kind=DraftKind.BLOG_POST).select_related("current_version"):
        if draft.current_version:
            titles.append(draft.current_version.content.get("title", ""))
    return [t for t in dict.fromkeys(titles) if t]


def propose_topics(run: AgentRun, reporter: RunReporter, cfg: ContentAgentConfig) -> list[BlogTopic]:
    project = run.project
    covered = covered_titles(project)
    rejected = list(BlogTopic.objects.filter(project=project, status=BlogTopic.Status.REJECTED)
                    .values_list("title", flat=True))
    reporter.step(f"Proposing {cfg.topics_per_run} blog topics")
    result = llm.complete("content.topics", {"count": cfg.topics_per_run, "covered": covered, "rejected": rejected},
                          project=project, run=run)
    created, skipped = [], 0
    for t in result.parsed.topics:
        if is_near_duplicate(t.title, covered + rejected + [c.title for c in created]):
            skipped += 1
            continue
        created.append(BlogTopic.objects.create(
            project=project, title=t.title.strip(), angle=t.angle, target_keywords=t.target_keywords,
            pillar=t.pillar, why=t.why, created_run=run, llm_call=result.call,
        ))
    run.stats.update(topics_proposed=len(created), topics_duplicate=skipped)
    run.save(update_fields=["stats"])
    reporter.success(f"Proposed {len(created)} new topic(s)" + (f", skipped {skipped} repeat(s)" if skipped else ""))
    return created


def post_variables(project, topic: BlogTopic, cfg: ContentAgentConfig, *, previous: dict | None = None,
                   instruction: str = "") -> dict:
    return {
        "project_name": project.name, "title": topic.title, "angle": topic.angle,
        "target_keywords": topic.target_keywords, "target_words": cfg.target_words, "guidance": cfg.guidance,
        "disclaimer": policy_for(project).blog_disclaimer, "previous": previous, "instruction": instruction,
    }


def finalize_post(parsed, disclaimer: str = "") -> dict:
    """Deterministic clean-up of the model's post: a valid slug, and the policy's disclaimer if it has one."""
    body = parsed.body_md.strip()
    body = re.sub(r"\A#\s+.*\n+", "", body)  # the title is rendered separately; drop a stray H1
    if disclaimer and disclaimer.lower() not in body.lower():
        body += f"\n\n---\n\n*{disclaimer}*"
    return {
        "title": parsed.title.strip(),
        "meta_description": parsed.meta_description.strip(),
        "slug": slugify(parsed.slug or parsed.title),
        "keywords": [k.strip() for k in parsed.target_keywords if k.strip()],
        "body_md": body + "\n",
    }


def seo_flags(content: dict) -> list[dict]:
    flags = []
    if len(content["meta_description"]) > META_LIMIT:
        flags.append({"rule": "seo", "excerpt": content["meta_description"][:60] + "…",
                      "explanation": f"Meta description is {len(content['meta_description'])} characters; "
                                     f"search engines truncate after about {META_LIMIT}."})
    return flags


def draft_post(run: AgentRun, reporter: RunReporter, topic: BlogTopic, cfg: ContentAgentConfig) -> Draft | None:
    model_key, model = draft_model_for(run.project, AgentType.CONTENT)
    reporter.step(f"Writing “{topic.title[:70]}”", topic_id=topic.pk, draft_model=model_key)
    try:
        result = llm.complete("content.post", post_variables(run.project, topic, cfg), project=run.project, run=run,
                              model=model)
    except llm.LLMError as exc:
        reporter.error(f"Couldn't write “{topic.title[:70]}”: {exc}", exc=exc)
        return None
    content = finalize_post(result.parsed, policy_for(run.project).blog_disclaimer)
    draft = services.create_draft(run.project, agent_type=AgentType.CONTENT, kind=DraftKind.BLOG_POST,
                                  content=content, result=result, run=run, blog_topic=topic)
    compliance.lint(draft, run)
    if extra := seo_flags(content):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    topic.status = BlogTopic.Status.DRAFTED
    topic.save(update_fields=["status", "updated_at"])
    words = len(content["body_md"].split())
    reporter.success(f"Drafted “{content['title'][:70]}” ({words} words)")
    return draft


def run_content_agent(run: AgentRun, reporter: RunReporter) -> None:
    """Manual/scheduled run. params.topic_id drafts one specific topic (requested or from the backlog)."""
    project = run.project
    cfg = load_config(project)
    if topic_id := run.params.get("topic_id"):
        topic = BlogTopic.objects.get(pk=topic_id, project=project)
        drafted = draft_post(run, reporter, topic, cfg)
        run.stats["drafted"] = int(drafted is not None)
        run.save(update_fields=["stats"])
        return

    backlog = list(BlogTopic.objects.filter(project=project, status=BlogTopic.Status.PROPOSED)
                   .order_by("-requested_by_user", "created_at"))
    if len(backlog) < max(cfg.min_backlog, cfg.drafts_per_run):
        backlog += propose_topics(run, reporter, cfg)
    drafted = 0
    for topic in backlog[: cfg.drafts_per_run]:
        drafted += draft_post(run, reporter, topic, cfg) is not None
    run.stats["drafted"] = drafted
    run.save(update_fields=["stats"])


def regenerate(draft: Draft, nudge: str, instruction: str, run) -> DraftVersion:
    topic = draft.blog_topic
    if topic is None:
        raise ValueError("This draft has no topic")
    cfg = load_config(draft.project)
    text = nudge_instruction(nudge, instruction, draft.project.name)
    variables = post_variables(draft.project, topic, cfg, previous=draft.current_version.content, instruction=text)
    _, model = draft_model_for(draft.project, AgentType.CONTENT)
    result = llm.complete("content.post", variables, project=draft.project, run=run, model=model)
    content = finalize_post(result.parsed, policy_for(draft.project).blog_disclaimer)
    version = services.add_version(draft, content, source=DraftVersion.Source.AI_REGENERATED, result=result,
                                   nudge=nudge, instruction=instruction)
    compliance.lint(draft, run)
    if extra := seo_flags(content):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    return version
