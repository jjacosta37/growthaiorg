/**
 * The inbox: filter header, list rows, detail pane, keyboard shortcuts.
 * From "Helmly - App Shell.dc.html".
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ChannelBadge, FlagCount, ScorePill } from "../../components/badges";
import { DetailPane, ListPane } from "../../components/Shell";
import { EmptyState, ErrorState, ListSkeleton } from "../../components/feedback";
import { Kbd, Select, cx } from "../../components/primitives";
import { age } from "../../lib/format";
import { useDrafts, useMarkRead, type DraftFilters } from "../../lib/queries";
import type { DraftListItem, DraftStatus } from "../../lib/types";
import { DraftDetail } from "./DraftDetail";
import "./inbox.css";

const STATUS_OPTIONS: { value: DraftStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "posted", label: "Posted" },
  { value: "dismissed", label: "Dismissed" },
];

export default function InboxPage() {
  const params = useParams();
  const navigate = useNavigate();
  const selectedId = params.draftId ? Number(params.draftId) : null;

  const [filters, setFilters] = useState<DraftFilters>({
    agent: "all",
    status: "new",
    sort: "newest",
  });

  const drafts = useDrafts(filters);
  const items = useMemo(() => drafts.data?.results ?? [], [drafts.data]);
  const markRead = useMarkRead();
  const listRef = useRef<HTMLDivElement>(null);

  const select = useCallback(
    (draft: DraftListItem | undefined) => {
      if (!draft) return;
      navigate(`/inbox/${draft.id}`);
      if (draft.unread) markRead.mutate(draft.id);
    },
    [navigate, markRead],
  );

  // j/k move through the list. The detail pane owns c/e/r/d, since they act on
  // the open draft and need its state.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "j" && event.key !== "k") return;
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!items.length) return;

      event.preventDefault();
      const index = items.findIndex((item) => item.id === selectedId);
      const next =
        event.key === "j"
          ? Math.min(index + 1, items.length - 1)
          : Math.max(index - 1, 0);
      select(items[index === -1 ? 0 : next]);
    };

    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [items, selectedId, select]);

  // Keep the selected row in view when moving by keyboard.
  useEffect(() => {
    if (selectedId === null) return;
    listRef.current
      ?.querySelector(`[data-draft-id="${selectedId}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  return (
    <>
      <ListPane
        header={
          <>
            <Select
              aria-label="Filter by agent"
              value={filters.agent}
              onChange={(e) =>
                setFilters((f) => ({ ...f, agent: e.target.value as DraftFilters["agent"] }))
              }
            >
              <option value="all">All agents</option>
              <option value="reddit">Reddit</option>
              <option value="x">X</option>
              <option value="content">Blog</option>
            </Select>

            <Select
              aria-label="Filter by status"
              value={filters.status}
              onChange={(e) =>
                setFilters((f) => ({ ...f, status: e.target.value as DraftStatus }))
              }
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Sort"
              value={filters.sort}
              onChange={(e) =>
                setFilters((f) => ({ ...f, sort: e.target.value as DraftFilters["sort"] }))
              }
            >
              <option value="newest">Newest</option>
              <option value="score">Highest score</option>
            </Select>
          </>
        }
        footer={<ShortcutHints />}
      >
        <div ref={listRef}>
          {drafts.isLoading ? (
            <ListSkeleton />
          ) : drafts.isError ? (
            <ErrorState
              title="Couldn't load drafts"
              body="Check your connection."
              onRetry={() => void drafts.refetch()}
            />
          ) : items.length === 0 ? (
            <EmptyState
              title={filters.status === "new" ? "All caught up" : "Nothing here"}
              body={
                filters.status === "new"
                  ? "Nothing waiting in the inbox right now."
                  : `No ${filters.status} drafts${filters.agent !== "all" ? " for this agent" : ""}.`
              }
            />
          ) : (
            <div className="rows">
              {items.map((draft) => (
                <Row
                  key={draft.id}
                  draft={draft}
                  selected={draft.id === selectedId}
                  onSelect={() => select(draft)}
                />
              ))}
            </div>
          )}
        </div>
      </ListPane>

      <DetailPane>
        {selectedId === null ? (
          <EmptyState
            title="Nothing selected"
            body="Pick a draft from the list, or press j to start at the top."
          />
        ) : (
          <DraftDetail
            draftId={selectedId}
            onDone={() => {
              // After acting on a draft, move to the next one still in the list.
              const index = items.findIndex((item) => item.id === selectedId);
              const next = items[index + 1] ?? items[index - 1];
              if (next) select(next);
              else navigate("/inbox");
            }}
          />
        )}
      </DetailPane>
    </>
  );
}

function Row({
  draft,
  selected,
  onSelect,
}: {
  draft: DraftListItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      data-draft-id={draft.id}
      className={cx("row", selected && "row--selected", draft.unread && "row--unread")}
      onClick={onSelect}
    >
      <div className="row__main">
        <div className="row__top">
          <ChannelBadge channel={draft.channel} />
          {draft.score !== null && <ScorePill score={draft.score} />}
          <FlagCount count={draft.flag_count} />
          <span style={{ flex: 1 }} />
          <span className="row__meta">
            {age(draft.created_at)}
            {draft.unread && <span className="row__unread-dot" aria-label="Unread" />}
          </span>
        </div>
        <div className="row__title">{draft.title || "Untitled"}</div>
      </div>
    </button>
  );
}

/** The quiet, permanent shortcut hint from the designs. */
export function ShortcutHints() {
  return (
    <div className="shell__list-footer">
      <span>
        <Kbd>j</Kbd> <Kbd>k</Kbd> move
      </span>
      <span>
        <Kbd>c</Kbd> copy
      </span>
      <span>
        <Kbd>e</Kbd> edit
      </span>
      <span>
        <Kbd>r</Kbd> regenerate
      </span>
      <span>
        <Kbd>d</Kbd> dismiss
      </span>
    </div>
  );
}
