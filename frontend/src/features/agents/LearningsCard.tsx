/**
 * What the agent has learned from feedback: a short digest (editable) plus the raw entries it
 * came from. New feedback is folded in shortly after it's given; entries not yet folded in are
 * still passed to the agent directly, so nothing waits on the digest.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog, EmptyState, useToast } from "../../components/feedback";
import { Button, Field, IconButton, Textarea } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { FEEDBACK_SOURCE_LABEL, RATING_LABEL, plural, relative } from "../../lib/format";
import {
  useDeleteFeedback,
  useLearnings,
  useRebuildLearnings,
  useSaveLearnings,
} from "../../lib/queries";
import type { AgentType, FeedbackEntry } from "../../lib/types";

export function LearningsCard({ type }: { type: AgentType }) {
  const learnings = useLearnings(type);
  const save = useSaveLearnings(type);
  const rebuild = useRebuildLearnings(type);
  const remove = useDeleteFeedback(type);
  const toast = useToast();
  const [writing, setWriting] = useState("");
  const [selection, setSelection] = useState("");
  const [confirmRebuild, setConfirmRebuild] = useState(false);

  const data = learnings.data;
  // Follow the server after a save, a digest or a refetch.
  useEffect(() => {
    if (data) {
      setWriting(data.writing);
      setSelection(data.selection);
    }
  }, [data?.writing, data?.selection]);

  if (!data) return null;
  const dirty = writing !== data.writing || selection !== data.selection;
  const onError = (fallback: string) => (error: unknown) =>
    toast.error(error instanceof ApiError ? error.detail : fallback);

  return (
    <section className="card">
      <div className="card__header">
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="card__title">Learnings</span>
          <span className="subtle">
            {data.digesting
              ? "Updating from new feedback…"
              : data.pending
                ? `${plural(data.pending, "new entry", "new entries")} not folded in yet (already used in new drafts)`
                : data.source === "human"
                  ? `Edited by you ${relative(data.updated_at)}`
                  : "Distilled from your feedback on drafts. Edit freely."}
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          disabled={!data.entries.length && !data.writing && !data.selection}
          loading={rebuild.isPending}
          onClick={() => setConfirmRebuild(true)}
        >
          Rebuild
        </Button>
      </div>

      <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
        <Field label="Writing" hint="How replies should be written. Given to every draft.">
          <Textarea
            rows={5}
            maxLength={4000}
            value={writing}
            onChange={(e) => setWriting(e.target.value)}
            placeholder="Nothing yet. Leave feedback on a draft in the inbox and the lessons show up here."
          />
        </Field>
        <Field label="Post selection" hint="Which posts are worth a reply. Given to the scoring step.">
          <Textarea
            rows={3}
            maxLength={4000}
            value={selection}
            onChange={(e) => setSelection(e.target.value)}
            placeholder="Nothing yet."
          />
        </Field>
        {dirty && (
          <div className="row-flex" style={{ gap: "var(--space-2)", justifyContent: "flex-end" }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setWriting(data.writing);
                setSelection(data.selection);
              }}
            >
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  { writing, selection },
                  { onSuccess: () => toast.show("Learnings saved"), onError: onError("Couldn't save") },
                )
              }
            >
              Save changes
            </Button>
          </div>
        )}

        <Field label="Feedback given">
          {data.entries.length ? (
            <FeedbackList
              entries={data.entries}
              onDelete={(id) =>
                remove.mutate(id, {
                  onSuccess: () => toast.show("Feedback deleted. Rebuild to drop it from the learnings."),
                  onError: onError("Couldn't delete"),
                })
              }
            />
          ) : (
            <EmptyState
              title="No feedback yet"
              body="Use the Feedback box on a Reddit draft, or tick “Remember for future replies” when regenerating."
            />
          )}
        </Field>
      </div>

      <ConfirmDialog
        open={confirmRebuild}
        title="Rebuild learnings?"
        body="The learnings are rewritten from the feedback listed here. Hand edits are replaced."
        confirmLabel="Rebuild"
        busy={rebuild.isPending}
        onCancel={() => setConfirmRebuild(false)}
        onConfirm={() =>
          rebuild.mutate(undefined, {
            onSuccess: () => {
              setConfirmRebuild(false);
              toast.show("Rebuilding learnings");
            },
            onError: onError("Couldn't rebuild"),
          })
        }
      />
    </section>
  );
}

function FeedbackList({ entries, onDelete }: { entries: FeedbackEntry[]; onDelete: (id: number) => void }) {
  return (
    <ul className="feedback-list">
      {entries.map((entry) => (
        <li key={entry.id} className="feedback-list__item">
          <div className="stack" style={{ gap: "var(--space-1)", minWidth: 0 }}>
            <span>
              {entry.rating && <span aria-label={entry.rating}>{RATING_LABEL[entry.rating]} </span>}
              {entry.text || <span className="subtle">No comment</span>}
            </span>
            <span className="subtle">
              {FEEDBACK_SOURCE_LABEL[entry.source]} · {relative(entry.created_at)}
              {entry.draft && (
                <>
                  {" · "}
                  <Link to={`/inbox/${entry.draft}`}>{entry.draft_title || `Draft #${entry.draft}`}</Link>
                </>
              )}
            </span>
          </div>
          <IconButton label="Delete feedback" onClick={() => onDelete(entry.id)}>
            ×
          </IconButton>
        </li>
      ))}
    </ul>
  );
}
