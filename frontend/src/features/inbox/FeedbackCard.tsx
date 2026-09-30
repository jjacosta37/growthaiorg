/**
 * Feedback on a draft. It's remembered: folded into the agent's learnings and applied to
 * every future draft (see the Learnings card on the agent page).
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { useToast } from "../../components/feedback";
import { Button, Textarea, cx } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { FEEDBACK_SOURCE_LABEL, RATING_LABEL, relative } from "../../lib/format";
import { useDraftFeedback } from "../../lib/queries";
import type { DraftDetail, FeedbackRating } from "../../lib/types";

export function FeedbackCard({ draft }: { draft: DraftDetail }) {
  const [rating, setRating] = useState<FeedbackRating>("");
  const [text, setText] = useState("");
  const send = useDraftFeedback(draft.id);
  const toast = useToast();

  const submit = () =>
    send.mutate(
      { rating, text: text.trim() },
      {
        onSuccess: () => {
          setRating("");
          setText("");
          toast.show("Thanks. Future replies will take this into account.");
        },
        onError: (error) => toast.error(error instanceof ApiError ? error.detail : "Couldn't save feedback"),
      },
    );

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Feedback</span>
        <Link className="subtle" to={`/agents/${draft.channel}`}>
          Remembered for future replies
        </Link>
      </div>
      <div className="card__body stack" style={{ gap: "var(--space-3)" }}>
        {draft.feedback.map((entry) => (
          <div key={entry.id} className="detail__version">
            <span style={{ flex: 1 }}>
              {entry.rating && `${RATING_LABEL[entry.rating]} `}
              {entry.text || <span className="subtle">No comment</span>}
            </span>
            <span className="subtle">
              {FEEDBACK_SOURCE_LABEL[entry.source]} · {relative(entry.created_at)}
            </span>
          </div>
        ))}

        <div className="row-flex" style={{ gap: "var(--space-2)" }}>
          {(["up", "down"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={rating === value}
              aria-label={value === "up" ? "Good reply" : "Bad reply"}
              className={cx("feedback-rating", rating === value && "feedback-rating--active")}
              onClick={() => setRating(rating === value ? "" : value)}
            >
              {RATING_LABEL[value]}
            </button>
          ))}
        </div>
        <Textarea
          rows={2}
          maxLength={2000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What worked, what didn't? e.g. “Too formal, and it answered a question they didn't ask.”"
        />
        <div className="row-flex" style={{ justifyContent: "flex-end" }}>
          <Button
            size="sm"
            variant="primary"
            disabled={!rating && !text.trim()}
            loading={send.isPending}
            onClick={submit}
          >
            Save feedback
          </Button>
        </div>
      </div>
    </section>
  );
}
