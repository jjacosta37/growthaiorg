"""Text helpers shared by agents: slugs and a cheap lexical near-duplicate check. Models are told
what already exists, but they still repeat themselves, so this backs that up."""

import re

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "your", "you", "how", "what", "why",
    "is", "are", "do", "does", "vs", "versus", "guide", "explained", "complete", "should", "can", "it", "its",
    "when", "which", "every", "strategies", "strategy", "benefits", "real", "world", "tips", "ways",
}


def slugify(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _stem(word: str) -> str:
    for suffix in ("ing", "ions", "ion", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def key_terms(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {_stem(w) for w in words if w not in STOPWORDS and len(w) > 1}


def is_near_duplicate(title: str, existing: list[str], threshold: float = 0.6) -> bool:
    """True if `title` shares most of its key terms with any existing title (Jaccard)."""
    terms = key_terms(title)
    if not terms:
        return False
    for other in existing:
        other_terms = key_terms(other)
        if not other_terms:
            continue
        overlap = len(terms & other_terms) / len(terms | other_terms)
        if overlap >= threshold or slugify(title) == slugify(other):
            return True
    return False
