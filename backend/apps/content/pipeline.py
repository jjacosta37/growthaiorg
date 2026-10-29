"""Content Agent: keep a backlog of blog topics backed by evidence, and draft full SEO posts from it.

A run gathers Reddit evidence, proposes topics when the backlog runs low, looks up search data
for new and pending topics, then drafts the highest-opportunity topics (`opportunity.py`).
"""

import re
from dataclasses import dataclass

import llm
from apps.agents.draft_models import draft_model_for
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter
from apps.context.models import CrawledPage
from apps.core.errors import public_message
from apps.core.models import Project
from apps.core.text import is_near_duplicate, slugify
from apps.inbox import compliance, services
from apps.inbox.models import Draft, DraftKind, DraftVersion
from apps.inbox.nudges import nudge_instruction
from apps.policy.service import policy_for, with_blog_disclaimer
from apps.publishing import services as publishing
from apps.reddit.models import RedditPost
from llm.models import LLMCall
from llm.schemas import TopicProposal

from . import keywords
from .config import ContentAgentConfig
from .models import BlogTopic
from .opportunity import rank_topics, with_evidence_count
from .research import gather_evidence, prompt_posts

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


@dataclass
class Proposal:
    """A topic the model proposed, held until its search data decides whether it's kept."""

    topic: TopicProposal
    evidence: list[RedditPost]
    keywords: list[str]
    call: LLMCall | None


def propose_topics(run: AgentRun, reporter: RunReporter, cfg: ContentAgentConfig) -> list[Proposal]:
    """Ask the model for new topics, grounded in the project's Reddit evidence.

    Evidence ids are checked against the posts that were sent, and each post backs at most one
    topic. Near-duplicates of anything covered or rejected are dropped. Nothing is saved yet:
    `save_proposals` keeps or drops each proposal once its search data is known.
    """
    project = run.project
    posts = gather_evidence(run, reporter)
    by_id = {p.pk: p for p in posts}
    covered = covered_titles(project)
    rejected = list(BlogTopic.objects.filter(project=project, status=BlogTopic.Status.REJECTED)
                    .values_list("title", flat=True))
    reporter.step(f"Proposing {cfg.topics_per_run} blog topics")
    result = llm.complete("content.topics", {"count": cfg.topics_per_run, "covered": covered, "rejected": rejected,
                                             "posts": prompt_posts(posts)},
                          project=project, run=run)
    proposals: list[Proposal] = []
    used: set[int] = set()
    duplicates = 0
    for t in result.parsed.topics:
        if len(proposals) == cfg.topics_per_run:
            break  # the model's output never sets how many topics are kept
        if is_near_duplicate(t.title, covered + rejected + [p.topic.title for p in proposals]):
            duplicates += 1
            continue
        evidence = [by_id[i] for i in dict.fromkeys(t.evidence_post_ids) if i in by_id and i not in used]
        used.update(p.pk for p in evidence)
        proposals.append(Proposal(topic=t, evidence=evidence, call=result.call,
                                  keywords=keywords.candidate_keywords(t.target_keywords, t.title)))
    run.stats.update(topics_duplicate=duplicates, posts_grouped=len(used),
                     topics_with_evidence=sum(bool(p.evidence) for p in proposals))
    run.save(update_fields=["stats"])
    reporter.event(
        f"Model proposed {len(proposals)} topic(s) from {len(used)} of {len(posts)} post(s)"
        + (f", skipped {duplicates} repeat(s)" if duplicates else ""),
        proposed=len(proposals), duplicates=duplicates, posts_considered=len(posts), posts_grouped=len(used),
        groups=[{"title": p.topic.title[:80], "posts": len(p.evidence)} for p in proposals],
    )
    return proposals


def pending_topics(project: Project) -> list[BlogTopic]:
    """Topics waiting for search data, oldest first. Drafted and rejected topics aren't looked up."""
    return list(BlogTopic.objects.filter(project=project, status=BlogTopic.Status.PROPOSED,
                                         search_status=BlogTopic.SearchStatus.PENDING).order_by("created_at"))


def save_proposals(run: AgentRun, reporter: RunReporter, cfg: ContentAgentConfig,
                   proposals: list[Proposal]) -> list[BlogTopic]:
    """Look up search data for new proposals and pending topics, then save the proposals worth keeping.

    New proposals are looked up first, then pending topics, oldest first, within the per-run
    budget. A proposal with no Reddit evidence whose keywords have no search volume is dropped;
    one whose lookup is still pending is kept as pending.

    Returns:
        The topics saved from `proposals`.
    """
    pending = pending_topics(run.project)
    outcome = keywords.look_up(
        run, reporter, cfg,
        [p.keywords for p in proposals] + [keywords.candidate_keywords(t.target_keywords, t.title) for t in pending],
    )
    for topic, data in zip(pending, outcome.data[len(proposals):], strict=True):
        if data is not None:
            keywords.apply_search_data(topic, data, cfg)
            topic.save(update_fields=keywords.SEARCH_FIELDS)

    saved, no_demand = [], 0
    for proposal, data in zip(proposals, outcome.data[: len(proposals)], strict=True):
        if not proposal.evidence and data is not None and data.volume == 0:
            no_demand += 1
            continue
        t = proposal.topic
        topic = BlogTopic(project=run.project, title=t.title.strip(), angle=t.angle,
                          target_keywords=[k.strip() for k in t.target_keywords if k.strip()][:keywords.MAX_CANDIDATES],
                          pillar=t.pillar, why=t.why, created_run=run, llm_call=proposal.call)
        if data is not None:
            keywords.apply_search_data(topic, data, cfg)
        topic.save()
        topic.evidence_posts.set(proposal.evidence)
        saved.append(topic)
    if proposals:
        run.stats.update(topics_proposed=len(saved), topics_no_demand=no_demand)
        run.save(update_fields=["stats"])
        reporter.success(
            f"Proposed {len(saved)} new topic(s)"
            + (f", dropped {no_demand} with no Reddit evidence and no search volume" if no_demand else ""),
            proposed=len(saved), dropped_no_demand=no_demand, pending=sum(t.search_status == "pending" for t in saved),
        )
    return saved


def ensure_search_data(run: AgentRun, reporter: RunReporter, cfg: ContentAgentConfig, topic: BlogTopic) -> None:
    """Look up a single topic's search data before drafting it, if it's still pending."""
    if topic.search_status != BlogTopic.SearchStatus.PENDING:
        return
    outcome = keywords.look_up(run, reporter, cfg, [keywords.candidate_keywords(topic.target_keywords, topic.title)])
    if outcome.data[0] is not None:
        keywords.apply_search_data(topic, outcome.data[0], cfg)
        topic.save(update_fields=keywords.SEARCH_FIELDS)


def post_variables(project: Project, topic: BlogTopic, cfg: ContentAgentConfig, *, previous: dict | None = None,
                   instruction: str = "") -> dict:
    """Prompt variables for writing a post: the topic, its primary keyword and the post settings.

    Args:
        previous: The current version's content, when revising one.
        instruction: The revision direction (preset nudge text plus the user's instruction).
    """
    return {
        "project_name": project.name, "title": topic.title, "angle": topic.angle,
        "primary_keyword": topic.primary_keyword, "target_keywords": topic.target_keywords,
        "target_words": cfg.target_words, "guidance": cfg.guidance,
        "disclaimer": policy_for(project).blog_disclaimer, "previous": previous, "instruction": instruction,
    }


def finalize_post(parsed, disclaimer: str = "") -> dict:
    """Deterministic clean-up of the model's post: a valid slug, and the policy's disclaimer if it has one."""
    body = parsed.body_md.strip()
    body = re.sub(r"\A#\s+.*\n+", "", body)  # the title is rendered separately; drop a stray H1
    body = with_blog_disclaimer(body, disclaimer)
    return {
        "title": parsed.title.strip(),
        "meta_description": parsed.meta_description.strip(),
        # A title with no Latin letters or digits slugifies to "", which the content schema refuses.
        "slug": slugify(parsed.slug or parsed.title) or slugify(parsed.title) or "post",
        "keywords": [k.strip() for k in parsed.target_keywords if k.strip()],
        "body_md": body + "\n",
    }


def keyword_placement(content: dict, keyword: str) -> list[str]:
    """Where the primary keyword is missing: "title", "first paragraph" and/or "H2"."""
    kw = " ".join(keyword.lower().split())
    body = content["body_md"]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not p.lstrip().startswith("#")]
    h2s = re.findall(r"^##\s+(.+)$", body, re.M)
    missing = []
    if kw not in " ".join(content["title"].lower().split()):
        missing.append("title")
    if not paragraphs or kw not in " ".join(paragraphs[0].lower().split()):
        missing.append("first paragraph")
    if not any(kw in " ".join(h.lower().split()) for h in h2s):
        missing.append("H2")
    return missing


def seo_flags(content: dict, primary_keyword: str = "") -> list[dict]:
    """Checks in code that the post prompt asks for: meta description length and keyword placement."""
    flags = []
    if len(content["meta_description"]) > META_LIMIT:
        flags.append({"rule": "seo", "excerpt": content["meta_description"][:60] + "…",
                      "explanation": f"Meta description is {len(content['meta_description'])} characters; "
                                     f"search engines truncate after about {META_LIMIT}."})
    if primary_keyword and (missing := keyword_placement(content, primary_keyword)):
        flags.append({"rule": "seo", "excerpt": primary_keyword[:60],
                      "explanation": f"The primary keyword is missing from the {', '.join(missing)}."})
    return flags


def draft_post(run: AgentRun, reporter: RunReporter, topic: BlogTopic, cfg: ContentAgentConfig) -> Draft | None:
    """Write a post for `topic`, lint it, and mark the topic drafted. Returns None if the model call failed."""
    model_key, model = draft_model_for(run.project, AgentType.CONTENT)
    reporter.step(f"Writing “{topic.title[:70]}”", topic_id=topic.pk, draft_model=model_key)
    try:
        result = llm.complete("content.post", post_variables(run.project, topic, cfg), project=run.project, run=run,
                              model=model)
    except llm.LLMError as exc:
        reporter.error(f"Couldn't write “{topic.title[:70]}”: {public_message(exc)}", exc=exc)
        return None
    content = finalize_post(result.parsed, policy_for(run.project).blog_disclaimer)
    draft = services.create_draft(run.project, agent_type=AgentType.CONTENT, kind=DraftKind.BLOG_POST,
                                  content=content, result=result, run=run, blog_topic=topic)
    compliance.lint(draft, run)
    if extra := seo_flags(content, topic.primary_keyword):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    topic.status = BlogTopic.Status.DRAFTED
    topic.save(update_fields=["status", "updated_at"])
    words = len(content["body_md"].split())
    reporter.success(f"Drafted “{content['title'][:70]}” ({words} words)")
    publishing.after_draft_written(draft, run, reporter)
    return draft


def backlog(project: Project, cfg: ContentAgentConfig) -> list[BlogTopic]:
    """The proposed topics in drafting order (`rank_topics`)."""
    qs = with_evidence_count(BlogTopic.objects.filter(project=project, status=BlogTopic.Status.PROPOSED))
    return rank_topics(qs, cfg.weights)


def run_content_agent(run: AgentRun, reporter: RunReporter) -> None:
    """Manual/scheduled run. params.topic_id drafts one specific topic (requested or from the backlog).

    Otherwise: propose topics if the backlog is low, look up search data for new and pending
    topics, and draft the top `drafts_per_run` topics by opportunity.
    """
    project = run.project
    cfg = load_config(project)
    if topic_id := run.params.get("topic_id"):
        topic = BlogTopic.objects.get(pk=topic_id, project=project)
        ensure_search_data(run, reporter, cfg, topic)
        drafted = draft_post(run, reporter, topic, cfg)
        run.stats["drafted"] = int(drafted is not None)
        run.save(update_fields=["stats"])
        return

    waiting = BlogTopic.objects.filter(project=project, status=BlogTopic.Status.PROPOSED).count()
    proposals = propose_topics(run, reporter, cfg) if waiting < max(cfg.min_backlog, cfg.drafts_per_run) else []
    save_proposals(run, reporter, cfg, proposals)
    drafted = 0
    for topic in backlog(project, cfg)[: cfg.drafts_per_run]:
        drafted += draft_post(run, reporter, topic, cfg) is not None
    run.stats["drafted"] = drafted
    run.save(update_fields=["stats"])


def regenerate(draft: Draft, nudge: str, instruction: str, run: AgentRun) -> DraftVersion:
    """Write a new AI version of a blog draft, steered by a nudge and/or an instruction.

    Raises:
        ValueError: The draft has no topic.
    """
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
    if extra := seo_flags(content, topic.primary_keyword):
        draft.compliance_flags = [*draft.compliance_flags, *extra]
        draft.save(update_fields=["compliance_flags", "updated_at"])
    return version
