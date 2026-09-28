/**
 * Context: product summary, competitors, the six documents as tabs, re-crawl and
 * the crawled-pages list. From "Luka - Context.dc.html".
 */

import { useState } from "react";

import { DetailPane } from "../../components/Shell";
import {
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorState,
  useToast,
} from "../../components/feedback";
import { MarkdownEditor } from "../../components/markdown";
import { Button, CompetitorChips, Field, Tabs, Textarea } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { dateTime, relative } from "../../lib/format";
import {
  useContextDocs,
  useCrawledPages,
  useProject,
  useRecrawl,
  useRegenerateDoc,
  useRevisions,
  useUpdateDoc,
  useUpdateProject,
} from "../../lib/queries";
import type { DocKind, DocSource } from "../../lib/types";
import "./context.css";

const DOC_ORDER: DocKind[] = [
  "product",
  "audience",
  "brand_voice",
  "competitors",
  "content_strategy",
  "compliance",
];

const SOURCE_LABEL: Record<DocSource, string> = {
  ai: "Written by Luka",
  human: "Edited by you",
  template: "From your content policy",
};

export default function ContextPage() {
  const project = useProject();
  const docs = useContextDocs();
  const [active, setActive] = useState<DocKind>("product");
  const [recrawlOpen, setRecrawlOpen] = useState(false);

  if (docs.isError) {
    return (
      <DetailPane wide>
        <ErrorState title="Couldn't load the context" onRetry={() => void docs.refetch()} />
      </DetailPane>
    );
  }

  const byKind = new Map((docs.data ?? []).map((doc) => [doc.kind, doc]));
  const ordered = DOC_ORDER.filter((kind) => byKind.has(kind));
  const current = byKind.get(active) ?? byKind.get(ordered[0] ?? "product");

  return (
    <DetailPane wide>
      <div className="page">
        <header className="page__header">
          <div>
            <h1 className="page__title">Context</h1>
            {project.data?.website_url && (
              <a
                className="page__subtitle"
                href={project.data.website_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {project.data.website_url}
              </a>
            )}
          </div>
          <Button onClick={() => setRecrawlOpen(true)}>Re-crawl site</Button>
        </header>

        <ProjectCard />

        <section className="card">
          <div className="card__header" style={{ paddingBottom: 0, borderBottom: "none" }}>
            <Tabs
              value={active}
              onChange={setActive}
              tabs={ordered.map((kind) => ({
                value: kind,
                label: byKind.get(kind)!.title,
              }))}
            />
          </div>

          {current ? (
            <DocumentPanel key={current.kind} kind={current.kind} />
          ) : (
            <div className="card__body">
              <EmptyState
                title="No documents yet"
                body="Run onboarding to have Luka read your site."
              />
            </div>
          )}
        </section>

        <CrawledPages />
      </div>

      <RecrawlDialog open={recrawlOpen} onClose={() => setRecrawlOpen(false)} />
    </DetailPane>
  );
}

/* --------------------------------------------------------------- project */

function ProjectCard() {
  const project = useProject();
  const update = useUpdateProject();
  const toast = useToast();
  const [summary, setSummary] = useState<string | null>(null);

  if (!project.data) return null;
  const data = project.data;
  const draftSummary = summary ?? data.product_summary;

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">{data.name || "Your product"}</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
        <Field label="Summary">
          <Textarea
            rows={3}
            value={draftSummary}
            onChange={(e) => setSummary(e.target.value)}
          />
          {summary !== null && summary !== data.product_summary && (
            <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
              <Button variant="ghost" size="sm" onClick={() => setSummary(null)}>
                Discard
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={update.isPending}
                onClick={() =>
                  update.mutate(
                    { product_summary: summary },
                    {
                      onSuccess: () => {
                        setSummary(null);
                        toast.show("Summary saved");
                      },
                    },
                  )
                }
              >
                Save
              </Button>
            </div>
          )}
        </Field>

        <Field label="Competitors">
          <CompetitorChips
            values={data.competitors}
            onChange={(competitors) =>
              update.mutate(
                { competitors },
                { onSuccess: () => toast.show("Competitors saved") },
              )
            }
          />
        </Field>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- document */

function DocumentPanel({ kind }: { kind: DocKind }) {
  const docs = useContextDocs();
  const doc = docs.data?.find((d) => d.kind === kind);
  const save = useUpdateDoc(kind);
  const regenerate = useRegenerateDoc(kind);
  const toast = useToast();
  const [historyOpen, setHistoryOpen] = useState(false);
  const revisions = useRevisions(kind, historyOpen);

  if (!doc) return null;

  return (
    <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
      <div className="row-flex" style={{ gap: "var(--space-3)" }}>
        <span className="subtle">{SOURCE_LABEL[doc.source]}</span>
        <span className="subtle">·</span>
        <span className="subtle">Last updated {relative(doc.updated_at)}</span>
        <span style={{ flex: 1 }} />
        <Button size="sm" variant="ghost" onClick={() => setHistoryOpen(true)}>
          Revision history
        </Button>
        {doc.source !== "template" && (
          <Button
            size="sm"
            loading={regenerate.isPending}
            onClick={() =>
              regenerate.mutate(undefined, {
                onSuccess: () => toast.show("Regenerating — watch the status line"),
                onError: (error) =>
                  toast.error(error instanceof ApiError ? error.detail : "Couldn't regenerate"),
              })
            }
          >
            Regenerate
          </Button>
        )}
      </div>

      <MarkdownEditor
        value={doc.content_md}
        saving={save.isPending}
        onSave={(content) =>
          save.mutate(content, { onSuccess: () => toast.show("Document saved") })
        }
        {...(doc.source === "template"
          ? { readOnlyNote: "Rendered from your content policy — editing makes it yours." }
          : {})}
      />

      <Dialog
        open={historyOpen}
        title={`${doc.title} — revisions`}
        wide
        onClose={() => setHistoryOpen(false)}
        actions={
          <Button variant="primary" onClick={() => setHistoryOpen(false)}>
            Close
          </Button>
        }
      >
        <div style={{ maxHeight: 400, overflowY: "auto" }}>
          {revisions.data?.length ? (
            revisions.data.map((revision) => (
              <details key={revision.id} className="revision">
                <summary>
                  <span>{SOURCE_LABEL[revision.source]}</span>
                  <span className="subtle">{dateTime(revision.created_at)}</span>
                  {revision.model && <span className="subtle mono">{revision.model}</span>}
                </summary>
                <pre className="detail__version-view">{revision.content_md}</pre>
              </details>
            ))
          ) : (
            <p className="subtle">No earlier revisions.</p>
          )}
        </div>
      </Dialog>
    </div>
  );
}

/* ----------------------------------------------------------------- pages */

function CrawledPages() {
  const pages = useCrawledPages();
  const items = pages.data ?? [];

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Crawled pages</span>
        <span className="subtle">{items.length}</span>
      </div>
      <div className="card__body" style={{ padding: 0 }}>
        {items.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>URL</th>
                <th>Title</th>
                <th style={{ width: 90 }}>Size</th>
              </tr>
            </thead>
            <tbody>
              {items.map((page) => (
                <tr key={page.id}>
                  <td className="table__mono">
                    <a href={page.url} target="_blank" rel="noopener noreferrer">
                      {page.url}
                    </a>
                  </td>
                  <td>{page.title || <span className="subtle">—</span>}</td>
                  <td className="table__mono">{formatChars(page.chars)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No pages crawled yet" />
        )}
      </div>
    </section>
  );
}

function formatChars(chars: number): string {
  if (chars < 1000) return `${chars} ch`;
  return `${(chars / 1000).toFixed(1)}k ch`;
}

/* --------------------------------------------------------------- recrawl */

function RecrawlDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const recrawl = useRecrawl();
  const docs = useContextDocs();
  const toast = useToast();

  const edited = (docs.data ?? []).filter((doc) => doc.source === "human");

  const start = (overwrite: boolean) =>
    recrawl.mutate(
      { overwrite_edited: overwrite },
      {
        onSuccess: () => {
          onClose();
          toast.show("Re-crawl started — watch the status line");
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.detail : "Couldn't start the re-crawl"),
      },
    );

  return (
    <ConfirmDialog
      open={open}
      title="Re-crawl site?"
      confirmLabel={edited.length ? "Keep my edits" : "Re-crawl"}
      busy={recrawl.isPending}
      onCancel={onClose}
      onConfirm={() => start(false)}
    >
      <p className="dialog__text">
        Luka reads your site again and rewrites the documents it generated.
      </p>
      {edited.length > 0 && (
        <>
          <div className="banner banner--warning">
            You've edited {edited.length === 1 ? "one document" : `${edited.length} documents`} by
            hand: {edited.map((doc) => doc.title).join(", ")}.
          </div>
          <Button
            variant="danger"
            onClick={() => start(true)}
            loading={recrawl.isPending}
          >
            Overwrite my edits
          </Button>
        </>
      )}
    </ConfirmDialog>
  );
}
