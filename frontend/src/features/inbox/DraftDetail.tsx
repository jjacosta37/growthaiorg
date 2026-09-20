/**
 * The detail pane: renderer per kind, plus the shared actions bar, compliance flags,
 * version history and the "Did you post it?" prompt.
 *
 * From "Helmly - Detail Panes.dc.html".
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChannelBadge, StatusBadge } from "../../components/badges";
import {
  ConfirmDialog,
  Dialog,
  DetailSkeleton,
  DropdownMenu,
  ErrorState,
  useToast,
} from "../../components/feedback";
import { Button, Field, Select, TextInput, Textarea } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { DISMISS_REASON_LABEL, KIND_LABEL, dateTime, relative } from "../../lib/format";
import {
  useDismissDraft,
  useDraft,
  useEditDraft,
  useMarkPosted,
  useRegenerateDraft,
  useRestoreDraft,
} from "../../lib/queries";
import type { DismissReason, DraftContent, DraftDetail as Draft, Nudge } from "../../lib/types";
import { BlogRenderer } from "./BlogRenderer";
import { RedditRenderer } from "./RedditRenderer";
import { XRenderer } from "./XRenderer";

/** Draft ids the user copied this session, awaiting a "did you post it?" answer. */
const pendingPosts = new Set<number>();

export function DraftDetail({ draftId, onDone }: { draftId: number; onDone: () => void }) {
  const query = useDraft(draftId);
  const toast = useToast();

  const [editing, setEditing] = useState(false);
  const [draftContent, setDraftContent] = useState<DraftContent | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [postedOpen, setPostedOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [askPosted, setAskPosted] = useState(false);
  const [versionOpen, setVersionOpen] = useState<number | null>(null);

  const edit = useEditDraft(draftId);
  const regenerate = useRegenerateDraft(draftId);
  const markPosted = useMarkPosted(draftId);
  const dismiss = useDismissDraft(draftId);
  const restore = useRestoreDraft(draftId);

  const draft = query.data;
  const readOnly = !!draft && draft.status !== "new";

  // Leaving edit mode whenever the draft changes underneath keeps the editor from
  // showing a stale body after a regeneration lands.
  useEffect(() => {
    setEditing(false);
    setDraftContent(null);
  }, [draftId, draft?.versions.length]);

  const content = draftContent ?? draft?.content ?? null;

  const copyAndOpen = useCallback(async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft.copy_text);
      toast.show("Copied to clipboard");
    } catch {
      toast.error("Couldn't copy — select the text and copy manually");
      return;
    }
    if (draft.open_url) window.open(draft.open_url, "_blank", "noopener");
    pendingPosts.add(draft.id);
  }, [draft, toast]);

  // "Did you post it?" — shown when the tab regains focus after a Copy & open.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (draft && pendingPosts.has(draft.id) && draft.status === "new") setAskPosted(true);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [draft]);

  const runRegenerate = useCallback(
    (nudge: Nudge, instruction?: string) => {
      regenerate.mutate(
        { nudge, instruction },
        {
          onSuccess: () => toast.show("Regeneration started"),
          onError: (error) =>
            toast.error(error instanceof ApiError ? error.detail : "Couldn't regenerate"),
        },
      );
    },
    [regenerate, toast],
  );

  // c / e / r / d act on the open draft.
  const shortcutsRef = useRef({ copyAndOpen, runRegenerate, readOnly });
  shortcutsRef.current = { copyAndOpen, runRegenerate, readOnly };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const { copyAndOpen: copy, runRegenerate: regen, readOnly: locked } = shortcutsRef.current;
      if (event.key === "c") {
        event.preventDefault();
        void copy();
      } else if (event.key === "e" && !locked) {
        event.preventDefault();
        setEditing(true);
      } else if (event.key === "r" && !locked) {
        event.preventDefault();
        regen("");
      } else if (event.key === "d" && !locked) {
        event.preventDefault();
        setDismissOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const regenerating = useMemo(
    () => regenerate.isPending || regenerate.isSuccess,
    [regenerate.isPending, regenerate.isSuccess],
  );

  if (query.isLoading) return <DetailSkeleton />;
  if (query.isError || !draft || !content) {
    return (
      <ErrorState
        title="Couldn't load this draft"
        onRetry={() => void query.refetch()}
      />
    );
  }

  const renderer =
    draft.kind === "reddit_comment" ? (
      <RedditRenderer
        draft={draft}
        content={content as never}
        editing={editing}
        onChange={setDraftContent}
      />
    ) : draft.kind === "blog_post" ? (
      <BlogRenderer
        draft={draft}
        content={content as never}
        editing={editing}
        onChange={setDraftContent}
      />
    ) : (
      <XRenderer
        draft={draft}
        content={content as never}
        editing={editing}
        onChange={setDraftContent}
      />
    );

  return (
    <div className="detail">
      <header className="detail__bar">
        <div className="row-flex" style={{ gap: "var(--space-2)" }}>
          <ChannelBadge channel={draft.channel} />
          <span className="subtle">{KIND_LABEL[draft.kind]}</span>
          {readOnly && <StatusBadge status={draft.status} />}
        </div>

        <div className="row-flex" style={{ gap: "var(--space-2)" }}>
          {readOnly ? (
            <Button
              onClick={() =>
                restore.mutate(undefined, {
                  onSuccess: () => toast.show("Restored to the inbox"),
                })
              }
              loading={restore.isPending}
            >
              Restore
            </Button>
          ) : (
            <>
              <Button variant="ghost" shortcut="D" onClick={() => setDismissOpen(true)}>
                Dismiss
              </Button>

              {editing ? (
                <>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEditing(false);
                      setDraftContent(null);
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    loading={edit.isPending}
                    disabled={!draftContent}
                    onClick={() =>
                      draftContent &&
                      edit.mutate(draftContent, {
                        onSuccess: () => {
                          setEditing(false);
                          setDraftContent(null);
                          toast.show("Saved");
                        },
                        onError: (error) =>
                          toast.error(
                            error instanceof ApiError ? error.detail : "Couldn't save",
                          ),
                      })
                    }
                  >
                    Save
                  </Button>
                </>
              ) : (
                <>
                  <Button shortcut="E" onClick={() => setEditing(true)}>
                    Edit
                  </Button>

                  <DropdownMenu
                    align="right"
                    trigger={({ toggle }) => (
                      <Button onClick={toggle} loading={regenerate.isPending}>
                        Regenerate ▾
                      </Button>
                    )}
                    items={[
                      { label: "Shorter", onSelect: () => runRegenerate("shorter") },
                      { label: "More casual", onSelect: () => runRegenerate("more_casual") },
                      {
                        label: "Don't mention the product",
                        onSelect: () => runRegenerate("no_mention"),
                      },
                      "separator",
                      { label: "Custom instruction…", onSelect: () => setCustomOpen(true) },
                    ]}
                  />

                  <Button variant="secondary" onClick={() => setPostedOpen(true)}>
                    Mark as posted
                  </Button>

                  <Button variant="primary" shortcut="C" onClick={() => void copyAndOpen()}>
                    Copy &amp; open
                  </Button>
                </>
              )}
            </>
          )}
        </div>
      </header>

      <div className="detail__body">
        {regenerating && (
          <div className="banner banner--info">
            Regenerating — the new version will appear here when it's ready.
          </div>
        )}

        {readOnly && (
          <div className="banner banner--info">
            {draft.status === "posted" ? (
              <span>
                Posted {relative(draft.posted_at)}
                {draft.posted_url && (
                  <>
                    {" · "}
                    <a href={draft.posted_url} target="_blank" rel="noopener noreferrer">
                      view it ↗
                    </a>
                  </>
                )}
              </span>
            ) : (
              <span>
                Dismissed as{" "}
                {DISMISS_REASON_LABEL[draft.dismiss_reason]?.toLowerCase() ?? draft.dismiss_reason}
                {draft.dismiss_note && ` — ${draft.dismiss_note}`}
              </span>
            )}
          </div>
        )}

        {!!draft.compliance_flags.length && <ComplianceFlags draft={draft} />}

        {renderer}

        {draft.versions.length > 1 && (
          <VersionHistory draft={draft} onView={setVersionOpen} />
        )}
      </div>

      {askPosted && (
        <div className="detail__ask" role="dialog" aria-label="Did you post it?">
          <div className="stack" style={{ gap: "var(--space-1)", flex: 1 }}>
            <strong>Did you post it?</strong>
            <span className="subtle">You copied this a moment ago.</span>
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              pendingPosts.delete(draft.id);
              setAskPosted(false);
            }}
          >
            Not yet
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              pendingPosts.delete(draft.id);
              setAskPosted(false);
              setPostedOpen(true);
            }}
          >
            Yes, mark posted
          </Button>
        </div>
      )}

      <DismissDialog
        open={dismissOpen}
        busy={dismiss.isPending}
        onCancel={() => setDismissOpen(false)}
        onConfirm={(reason, note) =>
          dismiss.mutate(
            { reason, note },
            {
              onSuccess: () => {
                setDismissOpen(false);
                toast.show("Dismissed");
                onDone();
              },
              onError: (error) =>
                toast.error(error instanceof ApiError ? error.detail : "Couldn't dismiss"),
            },
          )
        }
      />

      <MarkPostedDialog
        open={postedOpen}
        busy={markPosted.isPending}
        onCancel={() => setPostedOpen(false)}
        onConfirm={(url) =>
          markPosted.mutate(url, {
            onSuccess: () => {
              setPostedOpen(false);
              pendingPosts.delete(draft.id);
              toast.show("Marked as posted");
              onDone();
            },
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.detail : "Couldn't mark posted"),
          })
        }
      />

      <CustomNudgeDialog
        open={customOpen}
        busy={regenerate.isPending}
        onCancel={() => setCustomOpen(false)}
        onConfirm={(instruction) => {
          setCustomOpen(false);
          runRegenerate("custom", instruction);
        }}
      />

      <Dialog
        open={versionOpen !== null}
        title="Version"
        wide
        onClose={() => setVersionOpen(null)}
        actions={
          <Button variant="primary" onClick={() => setVersionOpen(null)}>
            Close
          </Button>
        }
      >
        <pre className="detail__version-view">
          {JSON.stringify(
            draft.versions.find((v) => v.id === versionOpen)?.content ?? {},
            null,
            2,
          )}
        </pre>
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------ compliance */

function ComplianceFlags({ draft }: { draft: Draft }) {
  const count = draft.compliance_flags.length;
  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">
          Compliance — {count} flag{count === 1 ? "" : "s"}
        </span>
        <span className="subtle">Warnings only. Nothing is blocked.</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-4)" }}>
        {draft.compliance_flags.map((flag, index) => (
          <div key={index} className="stack" style={{ gap: "var(--space-2)" }}>
            <div className="row-flex" style={{ gap: "var(--space-2)" }}>
              <span className="flag">
                <span aria-hidden>⚠</span>
                {flag.rule}
              </span>
            </div>
            {flag.excerpt && <blockquote className="detail__excerpt">"{flag.excerpt}"</blockquote>}
            <span className="muted">{flag.explanation}</span>
            {flag.excerpt && (
              <button
                type="button"
                className="toast__action"
                style={{ alignSelf: "flex-start" }}
                onClick={() => {
                  const body = document.querySelector(".detail__body");
                  const walker = body && document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
                  while (walker?.nextNode()) {
                    const node = walker.currentNode;
                    if (node.textContent?.includes(flag.excerpt)) {
                      (node.parentElement as HTMLElement | null)?.scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                      });
                      return;
                    }
                  }
                }}
              >
                Jump to excerpt →
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- history */

const VERSION_SOURCE_LABEL: Record<string, string> = {
  ai_initial: "AI original",
  ai_regenerated: "Regenerated",
  human_edit: "Your edit",
};

function VersionHistory({ draft, onView }: { draft: Draft; onView: (id: number) => void }) {
  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Version history</span>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-2)" }}>
        {[...draft.versions].reverse().map((version, index) => (
          <div key={version.id} className="detail__version">
            <span style={{ flex: 1 }}>
              {VERSION_SOURCE_LABEL[version.source] ?? version.source}
              {version.nudge && <span className="subtle"> · {version.nudge}</span>}
              {version.instruction && <span className="subtle"> — "{version.instruction}"</span>}
              {index === 0 && <span className="subtle"> · current</span>}
            </span>
            <span className="subtle">{dateTime(version.created_at)}</span>
            <button type="button" className="toast__action" onClick={() => onView(version.id)}>
              View
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- dialogs */

function DismissDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (reason: DismissReason, note: string) => void;
}) {
  const [reason, setReason] = useState<DismissReason>("not_relevant");
  const [note, setNote] = useState("");

  return (
    <ConfirmDialog
      open={open}
      title="Dismiss this draft?"
      confirmLabel="Dismiss"
      danger
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => onConfirm(reason, note)}
    >
      <Field label="Reason">
        <Select value={reason} onChange={(e) => setReason(e.target.value as DismissReason)}>
          {Object.entries(DISMISS_REASON_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Note" hint="Optional. Helps tune the agent later.">
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
      </Field>
    </ConfirmDialog>
  );
}

function MarkPostedDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  return (
    <ConfirmDialog
      open={open}
      title="Mark as posted"
      confirmLabel="Mark posted"
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => onConfirm(url.trim())}
    >
      <Field label="Posted URL" hint="Optional — a link back to where it went live.">
        <TextInput
          placeholder="https://"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          autoFocus
        />
      </Field>
    </ConfirmDialog>
  );
}

function CustomNudgeDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (instruction: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  return (
    <ConfirmDialog
      open={open}
      title="Regenerate with an instruction"
      confirmLabel="Regenerate"
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => instruction.trim() && onConfirm(instruction.trim())}
    >
      <Field label="What should change?">
        <Textarea
          autoFocus
          rows={3}
          placeholder="Lead with the concrete example instead of the principle."
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
        />
      </Field>
    </ConfirmDialog>
  );
}
