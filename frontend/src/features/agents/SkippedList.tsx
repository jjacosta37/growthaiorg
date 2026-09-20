/**
 * Reddit's skipped list: scanned posts that weren't drafted, sorted by score.
 * It exists to tune the threshold, so it leads with how many landed just below it.
 */

import { useMemo, useState } from "react";

import { ScorePill } from "../../components/badges";
import { EmptyState } from "../../components/feedback";
import { Segmented } from "../../components/primitives";
import { age, plural } from "../../lib/format";
import { useSkippedPosts } from "../../lib/queries";

type Band = "all" | "near";

export function SkippedList({ threshold }: { threshold: number }) {
  const [band, setBand] = useState<Band>("near");
  // "Near miss" is the 10 points below the threshold — the band worth reviewing.
  const nearFloor = Math.max(0, threshold - 10);
  const skipped = useSkippedPosts(band === "near" ? nearFloor : undefined);

  const posts = skipped.data?.results ?? [];
  const nearCount = useMemo(
    () =>
      posts.filter(
        (p) => p.relevance_score !== null && p.relevance_score >= nearFloor && p.relevance_score < threshold,
      ).length,
    [posts, nearFloor, threshold],
  );

  return (
    <section className="card">
      <div className="card__header">
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="card__title">Skipped</span>
          {band === "near" && nearCount > 0 && (
            <span className="subtle">
              {plural(nearCount, "post")} scored {nearFloor}–{threshold - 1} — the threshold
              could come down a little.
            </span>
          )}
        </div>
        <Segmented<Band>
          value={band}
          onChange={setBand}
          ariaLabel="Score band"
          options={[
            { value: "near", label: "Near miss" },
            { value: "all", label: "All" },
          ]}
        />
      </div>

      <div className="card__body" style={{ padding: 0 }}>
        {posts.length ? (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 56 }}>Score</th>
                <th>Post</th>
                <th style={{ width: 110 }}>Subreddit</th>
                <th style={{ width: 60 }}>Age</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((post) => (
                <tr key={post.id}>
                  <td>
                    {post.relevance_score !== null ? (
                      <ScorePill score={post.relevance_score} />
                    ) : (
                      <span className="subtle">—</span>
                    )}
                  </td>
                  <td>
                    <div className="stack" style={{ gap: "var(--space-1)" }}>
                      <a href={post.url} target="_blank" rel="noopener noreferrer">
                        {post.title}
                      </a>
                      {post.relevance_reason && (
                        <span className="subtle">{post.relevance_reason}</span>
                      )}
                      {post.score_error && (
                        <span style={{ color: "var(--color-danger)" }}>{post.score_error}</span>
                      )}
                    </div>
                  </td>
                  <td className="table__mono">r/{post.subreddit}</td>
                  <td>{age(post.posted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState
            title="Nothing skipped"
            body={
              band === "near"
                ? `No posts scored between ${nearFloor} and ${threshold - 1}.`
                : "Every scanned post was drafted."
            }
          />
        )}
      </div>
    </section>
  );
}
