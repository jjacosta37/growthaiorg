"""Onboarding: crawl the website, then write the context documents from it.

Deterministic steps; the LLM is only called inside individual steps. The crawled pages go into
the cached system prefix (`extra_cached`), so the five document calls in a row pay for them once.
"""

import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import llm
from apps.agents.models import AgentConfig, AgentRun, AgentType, ExternalUsage
from apps.agents.runs import RunReporter
from apps.agents.schedule import sync_periodic_task
from apps.core.models import Project
from apps.policy.models import ContentPolicy
from apps.policy.packs import all_packs, get_pack
from apps.policy.service import apply_pack, policy_for, render_compliance_doc
from providers.crawl import ApifyRenderer, crawl_site
from providers.crawl.urls import normalize

from .documents import is_human_edited, ordered_documents, save_document
from .models import CrawledPage, DocKind, DocSource

# AI-written docs, in generation order. Compliance comes from a template instead.
AI_DOCS = [DocKind.PRODUCT, DocKind.AUDIENCE, DocKind.BRAND_VOICE, DocKind.COMPETITORS, DocKind.CONTENT_STRATEGY]


def normalize_homepage(url: str) -> str:
    """Models often write bare domains ("empower.com"); store a full URL or nothing."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    return (normalize(url) or "").rstrip("/")


# --- Crawl ------------------------------------------------------------------------------


def page_renderer():
    """Browser renderer for JavaScript-only pages, if configured."""
    if not settings.APIFY_TOKEN:
        return None
    return ApifyRenderer(settings.APIFY_TOKEN, settings.APIFY_RENDER_ACTOR)


def crawl_and_store(project, reporter: RunReporter, max_pages: int) -> list[CrawledPage]:
    renderer = page_renderer()
    result = crawl_site(project.website_url, max_pages, progress=reporter.step,
                        delay_seconds=settings.CRAWL_DELAY_SECONDS, renderer=renderer)
    if result.render is not None:
        r = result.render
        ExternalUsage.objects.create(
            project=project, agent_run=reporter.run, provider=r.provider, purpose="render_pages",
            resource_id=settings.APIFY_RENDER_ACTOR, external_run_id=r.external_id, items=len(r.pages),
            cost_usd=r.cost_usd, error=r.error,
        )
        rendered = sum(p.rendered for p in result.pages)
        reporter.event(f"Rendered {rendered} JavaScript page(s) (${r.cost_usd:.3f})")
        if r.error:
            reporter.warning(f"Browser rendering had a problem: {r.error}")
    if thin := result.thin_pages:
        hint = "" if renderer else " Set APIFY_TOKEN to render them with a browser."
        reporter.warning(
            f"{len(thin)} page(s) only render with JavaScript, so Helmly has just their title and "
            f"description: {', '.join(p.url for p in thin[:5])}{'…' if len(thin) > 5 else ''}.{hint}"
        )
    with transaction.atomic():
        CrawledPage.objects.filter(project=project).delete()
        pages = CrawledPage.objects.bulk_create(
            CrawledPage(
                project=project,
                url=p.url,
                title=p.title[:500],
                content_text=p.text,
                content_hash=hashlib.sha256(p.text.encode()).hexdigest(),
            )
            for p in result.pages
        )
    reporter.run.stats.update(
        pages_discovered=result.discovered, pages_crawled=len(pages), pages_skipped=len(result.skipped),
        pages_thin=len(result.thin_pages), pages_rendered=sum(p.rendered for p in result.pages),
        discovery=result.discovery,
    )
    reporter.run.save(update_fields=["stats"])
    reporter.success(f"Crawled {len(pages)} pages", skipped=result.skipped[:50])
    return pages


def render_site_block(project, pages: list[CrawledPage]) -> tuple[str, int]:
    """Deterministic text of the crawled site for the cached prefix. Returns (text, pages_left_out)."""
    per_page = settings.CONTEXT_PAGE_CHAR_LIMIT
    budget = settings.CONTEXT_SITE_CHAR_BUDGET
    parts = [f"# Website content\n\nPages crawled from {project.website_url} (main text only)."]
    used = 0
    left_out = 0
    for page in pages:
        text = page.content_text[:per_page]
        if used + len(text) > budget:
            left_out += 1
            continue
        used += len(text)
        parts.append(f'<page url="{page.url}" title="{page.title}">\n{text}\n</page>')
    return "\n\n".join(parts), left_out


# --- Documents --------------------------------------------------------------------------


def generate_document(project, kind: str, run: AgentRun, site_block: str):
    others = [(d.title, d.content_md) for d in ordered_documents(project, exclude=kind)]
    variables = {
        "project_name": project.name,
        "website_url": project.website_url,
        "other_docs": others,
        "known_competitors": project.competitors,
    }
    result = llm.complete(f"context.{kind}", variables, project=project, run=run, extra_cached=site_block)
    return save_document(
        project, kind, result.text, source=DocSource.AI, prompt_version=result.prompt_version,
        model=result.model, llm_call=result.call,
    )


def write_compliance_doc(project):
    """The Compliance Guidelines doc, rendered from the project's policy pack and rules."""
    text = render_compliance_doc(project)
    pack = policy_for(project).pack
    return save_document(project, DocKind.COMPLIANCE, text, source=DocSource.TEMPLATE, prompt_version=f"pack:{pack}")


def identify_project(project, run: AgentRun, reporter: RunReporter, site_block: str) -> None:
    """Name the product and suggest a policy pack, unless the user already set them."""
    policy = policy_for(project)
    name_is_default = project.name.strip() in ("", Project.DEFAULT_NAME)
    if not name_is_default and policy.source == ContentPolicy.Source.USER:
        return
    reporter.step("Identifying the product and its industry")
    packs = [{"id": p.id, "description": p.description} for p in all_packs()]
    result = llm.complete("context.identify", {"packs": packs}, project=project, run=run, extra_cached=site_block)
    ident = result.parsed
    if name_is_default and ident.product_name.strip():
        project.name = ident.product_name.strip()[:120]
        project.save(update_fields=["name"])
    if policy.source == ContentPolicy.Source.DEFAULT:
        pack_id = ident.industry_pack if ident.industry_pack in {p["id"] for p in packs} else "general"
        apply_pack(policy, pack_id, source=ContentPolicy.Source.SUGGESTED)
        reporter.success(f"Identified {project.name}; using the “{get_pack(pack_id).name}” content rules "
                         f"({ident.reason}). You can change them in Settings.")


def update_project_facts(project, run: AgentRun) -> None:
    docs = {d.kind: d.content_md for d in ordered_documents(project)}
    result = llm.complete(
        "context.extract_facts",
        {"product_doc": docs.get(DocKind.PRODUCT, ""), "competitors_doc": docs.get(DocKind.COMPETITORS, "")},
        project=project,
        run=run,
    )
    facts = result.parsed
    project.product_summary = facts.product_summary
    existing = {c["name"].lower() for c in project.competitors}
    for c in facts.competitors:  # merge: never drop competitors I added by hand
        if c.name.lower() not in existing:
            project.competitors.append({"name": c.name, "url": normalize_homepage(c.url)})
            existing.add(c.name.lower())
    project.save(update_fields=["product_summary", "competitors"])


def suggest_reddit_targets(project, run: AgentRun, reporter: RunReporter) -> None:
    """Suggest subreddits and keywords. Applied to the Reddit Agent config only if it's still empty."""
    docs = {d.kind: d.content_md for d in ordered_documents(project)}
    result = llm.complete(
        "context.reddit_suggestions",
        {
            "product_doc": docs.get(DocKind.PRODUCT, ""),
            "audience_doc": docs.get(DocKind.AUDIENCE, ""),
            "strategy_doc": docs.get(DocKind.CONTENT_STRATEGY, ""),
        },
        project=project,
        run=run,
    )
    s = result.parsed
    subreddits = list(dict.fromkeys(n.name.strip().removeprefix("r/").strip("/") for n in s.subreddits))
    keywords = list(dict.fromkeys(k.strip() for k in s.keywords if k.strip()))
    suggestion = {
        "subreddits": subreddits,
        "keywords": keywords,
        "reasons": {n.name.strip().removeprefix("r/"): n.reason for n in s.subreddits},
    }
    run.stats["reddit_suggestions"] = suggestion
    run.save(update_fields=["stats"])

    config = AgentConfig.for_project(project, AgentType.REDDIT)
    if not config.config.get("subreddits") and not config.config.get("keywords"):
        config.config = {**config.config, "subreddits": subreddits, "keywords": keywords}
        config.save(update_fields=["config", "updated_at"])
        # for_project() may have just created this config, so beat has never seen it.
        sync_periodic_task(config)
        reporter.success(f"Suggested {len(subreddits)} subreddits and {len(keywords)} keywords for the Reddit Agent")
    else:
        reporter.event("Reddit Agent already configured; suggestions saved on this run only")


# --- Pipelines --------------------------------------------------------------------------


def run_onboarding(run: AgentRun, reporter: RunReporter) -> None:
    """Crawl, then (re)write the AI docs. Used for first onboarding and for re-crawls.

    On re-crawl, docs I've edited by hand are kept unless params.overwrite_edited is true.
    """
    project = run.project
    if not project.website_url:
        raise ValueError("Set the website URL first")
    overwrite_edited = run.kind == AgentRun.Kind.ONBOARDING or run.params.get("overwrite_edited", False)
    max_pages = int(run.params.get("max_pages") or settings.CRAWL_MAX_PAGES)

    pages = crawl_and_store(project, reporter, max_pages)
    if not pages:
        raise RuntimeError("No readable pages found. Check the URL, or whether the site blocks crawlers.")
    if len(pages) < settings.CONTEXT_MIN_PAGES_WARNING:
        reporter.warning(
            f"Only {len(pages)} readable page(s) found. The documents will be thin; "
            "edit them by hand or check the site is server-rendered."
        )

    site_block, left_out = render_site_block(project, pages)
    if left_out:
        reporter.warning(f"{left_out} page(s) left out of the model input to stay within the size budget")

    try:
        identify_project(project, run, reporter, site_block)
    except llm.LLMError as exc:
        reporter.error(f"Couldn't identify the product: {exc}", exc=exc)

    for kind in AI_DOCS:
        title = DocKind(kind).label
        if not overwrite_edited and is_human_edited(project, kind):
            reporter.event(f"Kept {title} (edited by you)")
            continue
        reporter.step(f"Writing {title}")
        try:
            generate_document(project, kind, run, site_block)
            reporter.success(f"Wrote {title}")
        except llm.LLMError as exc:
            reporter.error(f"Couldn't write {title}: {exc}", exc=exc)

    if not is_human_edited(project, DocKind.COMPLIANCE):  # keep it in sync with the policy
        write_compliance_doc(project)
        reporter.success(f"Added Compliance Guidelines ({get_pack(policy_for(project).pack).name} rules)")

    for label, fn in (("Extracting product summary and competitors", lambda: update_project_facts(project, run)),
                      ("Suggesting subreddits and keywords", lambda: suggest_reddit_targets(project, run, reporter))):
        reporter.step(label)
        try:
            fn()
        except llm.LLMError as exc:
            reporter.error(f"{label} failed: {exc}", exc=exc)

    if project.onboarded_at is None:
        project.onboarded_at = timezone.now()
        project.save(update_fields=["onboarded_at"])
    reporter.success("Context is ready")


def run_regenerate_document(run: AgentRun, reporter: RunReporter) -> None:
    project = run.project
    kind = run.params["kind"]
    title = DocKind(kind).label
    if kind == DocKind.COMPLIANCE:
        write_compliance_doc(project)
        reporter.success(f"Rebuilt {title} from the content policy")
        return
    pages = list(CrawledPage.objects.filter(project=project))
    if not pages:
        raise RuntimeError("No crawled pages yet. Re-crawl the site first.")
    site_block, _ = render_site_block(project, pages)
    reporter.step(f"Writing {title}")
    generate_document(project, kind, run, site_block)
    if kind in (DocKind.PRODUCT, DocKind.COMPETITORS):
        update_project_facts(project, run)
    reporter.success(f"Wrote {title}")
