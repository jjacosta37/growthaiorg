/** Reddit comment: the source thread, the score, and an editable comment box. */

import { useState } from "react";

import { ScorePill } from "../../components/badges";
import { Textarea } from "../../components/primitives";
import { age, plural } from "../../lib/format";
import type { DraftDetail, RedditCommentContent } from "../../lib/types";

export function RedditRenderer({
  draft,
  content,
  editing,
  onChange,
}: {
  draft: DraftDetail;
  content: RedditCommentContent;
  editing: boolean;
  onChange: (next: RedditCommentContent) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const post = draft.source_post;

  return (
    <div className="stack" style={{ gap: "var(--space-5)" }}>
      {post && (
        <section className="card">
          <div className="card__body stack" style={{ gap: "var(--space-3)" }}>
            <div className="row-flex" style={{ gap: "var(--space-2)" }}>
              <span className="mono subtle">r/{post.subreddit}</span>
              <span className="subtle">·</span>
              <a href={post.url} target="_blank" rel="noopener noreferrer" className="subtle">
                view thread ↗
              </a>
            </div>

            <h2 style={{ fontSize: "var(--text-lg)", fontWeight: "var(--weight-semibold)" }}>
              {post.title}
            </h2>

            {post.body && (
              <div className="muted" style={{ lineHeight: "var(--leading-relaxed)" }}>
                <span className={expanded ? undefined : "detail__clamp"}>{post.body}</span>
                {post.body.length > 240 && (
                  <button
                    type="button"
                    className="toast__action"
                    style={{ display: "block", marginTop: "var(--space-2)" }}
                    onClick={() => setExpanded((v) => !v)}
                  >
                    {expanded ? "Show less" : "Show more"}
                  </button>
                )}
              </div>
            )}

            <div className="subtle">
              {plural(post.upvotes, "upvote")} · {plural(post.num_comments, "comment")} ·{" "}
              {age(post.posted_at)} ago
            </div>

            {post.relevance_score !== null && (
              <div className="row-flex" style={{ gap: "var(--space-3)" }}>
                <ScorePill score={post.relevance_score} />
                <span className="muted">{post.relevance_reason}</span>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="card">
        <div className="card__header">
          <span className="card__title">Your comment</span>
          {post?.author && <span className="subtle">Replying in r/{post.subreddit}</span>}
        </div>
        <div className="card__body stack" style={{ gap: "var(--space-3)" }}>
          {content.poster_read && content.poster_read.toLowerCase() !== "no cues" && (
            <span className="detail__poster-read">Written for: {content.poster_read}</span>
          )}
          {editing ? (
            <Textarea
              autoFocus
              rows={10}
              value={content.body}
              onChange={(e) => onChange({ ...content, body: e.target.value })}
            />
          ) : (
            <div className="detail__comment">{content.body}</div>
          )}
        </div>
      </section>
    </div>
  );
}
