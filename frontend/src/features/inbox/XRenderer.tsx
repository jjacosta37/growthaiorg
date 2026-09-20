/** X post / thread: stacked cards with a live character counter and over-limit state. */

import { CharCounter, Textarea, cx } from "../../components/primitives";
import { X_FORMAT_LABEL } from "../../lib/format";
import type { DraftDetail, XPostContent } from "../../lib/types";

export function XRenderer({
  draft,
  content,
  editing,
  onChange,
}: {
  draft: DraftDetail;
  content: XPostContent;
  editing: boolean;
  onChange: (next: XPostContent) => void;
}) {
  const limit = draft.char_limit ?? 280;
  const posts = content.posts ?? [];

  const update = (index: number, text: string) => {
    const next = [...posts];
    next[index] = text;
    onChange({ ...content, posts: next });
  };

  return (
    <div className="stack" style={{ gap: "var(--space-4)" }}>
      <div className="row-flex" style={{ gap: "var(--space-2)" }}>
        {content.format && (
          <span className="badge badge--neutral">
            {X_FORMAT_LABEL[content.format] ?? content.format}
          </span>
        )}
        {content.angle && <span className="subtle">{content.angle}</span>}
        {posts.length > 1 && (
          <span className="subtle">
            · {posts.length} posts
          </span>
        )}
      </div>

      <div className="xthread">
        {posts.map((post, index) => {
          const over = post.length > limit;
          return (
            <article key={index} className={cx("xpost", over && "xpost--over")}>
              <div className="xpost__avatar" aria-hidden />
              <div className="xpost__main">
                <div className="xpost__head">
                  <strong>You</strong>
                  <span className="subtle">@handle</span>
                  {posts.length > 1 && (
                    <span className="subtle mono">
                      {index + 1}/{posts.length}
                    </span>
                  )}
                </div>

                {editing ? (
                  <Textarea
                    autoFocus={index === 0}
                    rows={4}
                    invalid={over}
                    value={post}
                    onChange={(e) => update(index, e.target.value)}
                  />
                ) : (
                  <div className="xpost__body">{post}</div>
                )}

                <div className="xpost__foot">
                  <CharCounter count={post.length} limit={limit} />
                  {over && <span className="subtle">Over the limit — trim before posting.</span>}
                </div>
              </div>
              {index < posts.length - 1 && <span className="xthread__connector" aria-hidden />}
            </article>
          );
        })}
      </div>
    </div>
  );
}
