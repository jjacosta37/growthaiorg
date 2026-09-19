"""Policy packs: industry-specific content rules as data (policies/*.yaml).

Adding an industry is adding a YAML file. A pack can `extends:` another; its rules are appended to
the parent's (same id overrides), and `compliance_doc_extra` is appended to the parent's template.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings


class UnknownPack(KeyError):
    pass


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    description: str
    rules: list[dict] = field(default_factory=list)
    blog_disclaimer: str = ""
    compliance_doc: str = ""


def packs_dir() -> Path:
    return Path(settings.POLICY_PACKS_DIR)


@lru_cache(maxsize=1)
def _raw() -> dict[str, dict]:
    out = {}
    for path in sorted(packs_dir().glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[data["id"]] = data
    return out


def get_pack(pack_id: str) -> Pack:
    raw = _raw()
    if pack_id not in raw:
        raise UnknownPack(pack_id)
    data = raw[pack_id]
    parent = get_pack(data["extends"]) if data.get("extends") else None
    rules = {r["id"]: r for r in (parent.rules if parent else [])}
    for r in data.get("rules") or []:
        rules[r["id"]] = {"id": r["id"], "title": r["title"], "description": " ".join(r["description"].split())}
    doc = data.get("compliance_doc") or (parent.compliance_doc if parent else "")
    if extra := data.get("compliance_doc_extra"):
        doc = f"{doc.rstrip()}\n\n{extra}"
    return Pack(
        id=data["id"], name=data["name"], description=data.get("description", ""), rules=list(rules.values()),
        blog_disclaimer=data.get("blog_disclaimer", parent.blog_disclaimer if parent else "") or "",
        compliance_doc=doc,
    )


def all_packs() -> list[Pack]:
    return [get_pack(pid) for pid in _raw()]


def clear_cache() -> None:
    _raw.cache_clear()
