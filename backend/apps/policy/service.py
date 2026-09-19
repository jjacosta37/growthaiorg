from jinja2 import Template

from .models import DEFAULT_PACK, ContentPolicy
from .packs import get_pack


def policy_for(project) -> ContentPolicy:
    policy = ContentPolicy.objects.filter(project=project).first()
    if policy is None:
        policy = ContentPolicy(project=project)
        apply_pack(policy, DEFAULT_PACK, source=ContentPolicy.Source.DEFAULT)
    return policy


def guardrail_variables(project) -> dict:
    """Registered with llm.context: rendered into every LLM call's guardrails. Deterministic
    (fixed rule order, no timestamps), so it stays inside the cached prefix."""
    policy = policy_for(project)
    requires_disclosure = any(r["id"] == "missing_disclosure" for r in policy.rules)
    return {
        "project_name": project.name,
        "author_role": policy.author_role,
        "rules": policy.rules,
        "disclosure": policy.rendered_disclosure() if requires_disclosure else "",
        "blog_disclaimer": policy.blog_disclaimer,
    }


def apply_pack(policy: ContentPolicy, pack_id: str, *, source: str) -> ContentPolicy:
    """Replace the rules and disclaimer with a pack's. Author role and disclosure wording are kept."""
    pack = get_pack(pack_id)
    policy.pack = pack.id
    policy.rules = [dict(r) for r in pack.rules]
    policy.blog_disclaimer = pack.blog_disclaimer
    policy.source = source
    policy.save()
    return policy


def render_compliance_doc(project) -> str:
    policy = policy_for(project)
    pack = get_pack(policy.pack)
    return Template(pack.compliance_doc).render(
        project_name=project.name, rules=policy.rules, disclosure=policy.rendered_disclosure(),
        blog_disclaimer=policy.blog_disclaimer,
    ).strip() + "\n"
