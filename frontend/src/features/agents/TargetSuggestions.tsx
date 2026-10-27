/**
 * "Suggest more": new subreddits and keywords for the Reddit Agent, from its context and its own
 * run history. Nothing reaches the config until the user ticks suggestions and presses Add;
 * dismissed ones never come back. See docs/prds/0004-reddit-target-suggestions.md.
 */

import { useEffect, useMemo, useState } from "react";

import { EmptyState, useToast } from "../../components/feedback";
import { Button, IconButton } from "../../components/primitives";
import { ApiError } from "../../lib/api";
import { plural } from "../../lib/format";
import {
  useAddSuggestions,
  useDismissSuggestion,
  useRedditSuggestions,
  useSuggestTargets,
} from "../../lib/queries";
import type { TargetSuggestion } from "../../lib/types";

export function TargetSuggestions({ configDirty }: { configDirty: boolean }) {
  const suggestions = useRedditSuggestions();
  const suggest = useSuggestTargets();
  const add = useAddSuggestions();
  const dismiss = useDismissSuggestion();
  const toast = useToast();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const data = suggestions.data;
  // Forget ticks for suggestions that are gone (added, dismissed or replaced).
  useEffect(() => {
    if (!data) return;
    const live = new Set(
      [...data.subreddits, ...data.keywords].map((s) => s.id),
    );
    setSelected((prev) => new Set([...prev].filter((id) => live.has(id))));
  }, [data]);

  const picked = useMemo(
    () => ({
      subreddits:
        data?.subreddits.filter((s) => selected.has(s.id)).length ?? 0,
      keywords: data?.keywords.filter((s) => selected.has(s.id)).length ?? 0,
    }),
    [data, selected],
  );

  if (!data) return null;
  const busy = data.suggesting || suggest.isPending;
  const hasAny = data.subreddits.length > 0 || data.keywords.length > 0;
  const onError = (fallback: string) => (error: unknown) =>
    toast.error(error instanceof ApiError ? error.detail : fallback);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const startSuggest = () =>
    suggest.mutate(undefined, {
      onError: onError("Couldn't start suggesting"),
    });

  const addSelected = () =>
    add.mutate([...selected], {
      onSuccess: (result) => {
        setSelected(new Set());
        toast.show(
          `Added ${plural(result.added ?? 0, "suggestion")} to the configuration`,
        );
      },
      onError: onError("Couldn't add the suggestions"),
    });

  const group = (
    kind: "subreddits" | "keywords",
    title: string,
    items: TargetSuggestion[],
  ) => {
    if (!items.length) return null;
    const full = picked[kind] >= data.room[kind];
    return (
      <div className="stack" style={{ gap: "var(--space-2)" }}>
        <span className="card__title">{title}</span>
        {data.room[kind] === 0 && (
          <span className="subtle">
            The limit of {data.limits[kind]} {kind} is reached. Remove some from
            the configuration to add more.
          </span>
        )}
        {items.map((item) => {
          const checked = selected.has(item.id);
          const disabled = !checked && full;
          return (
            <div key={item.id} className="suggestion">
              <label className="suggestion__pick">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(item.id)}
                />
                <span className="stack" style={{ gap: "var(--space-1)" }}>
                  <span className="table__mono">
                    {kind === "subreddits" ? `r/${item.value}` : item.value}
                  </span>
                  {item.reason && <span className="subtle">{item.reason}</span>}
                </span>
              </label>
              <IconButton
                label="Dismiss: don't suggest this again"
                disabled={dismiss.isPending}
                onClick={() =>
                  dismiss.mutate(item.id, {
                    onError: onError("Couldn't dismiss"),
                  })
                }
              >
                ×
              </IconButton>
            </div>
          );
        })}
        {full && data.room[kind] > 0 && (
          <span className="subtle">
            Only{" "}
            {plural(
              data.room[kind],
              kind === "subreddits" ? "more subreddit" : "more keyword",
            )}{" "}
            fit under the limit of {data.limits[kind]}.
          </span>
        )}
      </div>
    );
  };

  return (
    <section className="card">
      <div className="card__header">
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span className="card__title">Suggestions</span>
          <span className="subtle">
            {busy
              ? "Looking at your context and recent runs…"
              : "New subreddits and keywords, based on your context and what recent runs found."}
          </span>
        </div>
        <Button size="sm" loading={busy} onClick={startSuggest}>
          Suggest more
        </Button>
      </div>

      {(hasAny || !busy) && (
        <div className="card__body stack" style={{ gap: "var(--space-5)" }}>
          {data.last_error && !busy && (
            <div
              className="banner banner--danger row-flex"
              style={{ justifyContent: "space-between" }}
            >
              <span>{data.last_error}</span>
              <Button size="sm" variant="ghost" onClick={startSuggest}>
                Retry
              </Button>
            </div>
          )}

          {hasAny ? (
            <>
              {group("subreddits", "Subreddits", data.subreddits)}
              {group("keywords", "Keywords", data.keywords)}
              <div
                className="row-flex"
                style={{ gap: "var(--space-3)", justifyContent: "flex-end" }}
              >
                {configDirty && (
                  <span className="subtle">
                    Save or reset your configuration changes first.
                  </span>
                )}
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!selected.size || configDirty}
                  loading={add.isPending}
                  onClick={addSelected}
                >
                  {selected.size ? `Add ${selected.size}` : "Add"}
                </Button>
              </div>
            </>
          ) : data.nothing_new && !busy ? (
            <EmptyState
              title="No new suggestions"
              body="Everything worth suggesting is already in your configuration or was dismissed."
            />
          ) : (
            !busy &&
            !data.last_error && (
              <EmptyState
                title="Running out of fresh posts?"
                body="Press Suggest more for subreddits and keywords the agent isn't searching yet."
              />
            )
          )}
        </div>
      )}
    </section>
  );
}
