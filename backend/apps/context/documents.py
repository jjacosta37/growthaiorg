from .models import ContextDocument, ContextDocumentRevision, DocKind, DocSource

KIND_ORDER = [k.value for k in DocKind]


def ordered_documents(project, *, exclude: str | None = None) -> list[ContextDocument]:
    docs = {d.kind: d for d in ContextDocument.objects.filter(project=project).exclude(content_md="")}
    return [docs[k] for k in KIND_ORDER if k in docs and k != exclude]


def context_documents_for_llm(project) -> list[tuple[str, str]]:
    """Registered with llm.context: the docs included (and cached) in every LLM call."""
    return [(d.title, d.content_md) for d in ordered_documents(project)]


def save_document(project, kind: str, content_md: str, *, source: str, prompt_version: str = "",
                  model: str = "", llm_call=None) -> ContextDocument:
    doc, _ = ContextDocument.objects.get_or_create(project=project, kind=kind)
    doc.content_md = content_md.strip() + "\n"
    doc.source = source
    doc.prompt_version = prompt_version
    doc.model = model
    doc.save()
    ContextDocumentRevision.objects.create(
        document=doc, content_md=doc.content_md, source=source, prompt_version=prompt_version,
        model=model, llm_call=llm_call,
    )
    return doc


def is_human_edited(project, kind: str) -> bool:
    return ContextDocument.objects.filter(project=project, kind=kind, source=DocSource.HUMAN).exists()
