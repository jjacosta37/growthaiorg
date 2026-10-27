/** Display helpers. Pure functions, unit-tested in format.test.ts. */

import type { AgentType, DraftKind, RepeatHint, RunStats, RunStatus } from "./types";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Compact age for list rows: "now", "4m", "3h", "2d", "5w". */
export function age(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const delta = Math.max(0, now - then);
  if (delta < MINUTE) return "now";
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}m`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h`;
  if (delta < 7 * DAY) return `${Math.floor(delta / DAY)}d`;
  return `${Math.floor(delta / (7 * DAY))}w`;
}

/** Relative phrase for headers: "2h ago", "yesterday", "in 3h". */
export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";

  const delta = then - now;
  const ahead = delta > 0;
  const abs = Math.abs(delta);

  if (abs < MINUTE) return ahead ? "in a moment" : "just now";

  let value: string;
  if (abs < HOUR) value = `${Math.round(abs / MINUTE)}m`;
  else if (abs < DAY) value = `${Math.round(abs / HOUR)}h`;
  else if (abs < 2 * DAY) return ahead ? "tomorrow" : "yesterday";
  else if (abs < 7 * DAY) value = `${Math.round(abs / DAY)}d`;
  else value = `${Math.round(abs / (7 * DAY))}w`;

  return ahead ? `in ${value}` : `${value} ago`;
}

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const DATE_ONLY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_TIME.format(d);
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_ONLY.format(d);
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

export function percent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return "—";
  return `${Math.round(fraction * 100)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/* ------------------------------------------------------------------ labels */

export const RATING_LABEL: Record<string, string> = { up: "👍", down: "👎" };

export const FEEDBACK_SOURCE_LABEL: Record<string, string> = {
  explicit: "Feedback",
  instruction: "Remembered instruction",
};

export const CHANNEL_LABEL: Record<AgentType, string> = {
  reddit: "Reddit",
  content: "Blog",
  x: "X",
};

export const AGENT_LABEL: Record<AgentType, string> = {
  reddit: "Reddit Agent",
  content: "Content Agent",
  x: "X Agent",
};

export const KIND_LABEL: Record<DraftKind, string> = {
  reddit_comment: "Reddit comment",
  x_post: "X post",
  x_thread: "X thread",
  blog_post: "Blog post",
};

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  waiting_batch: "Waiting for batch",
  succeeded: "Succeeded",
  partial: "Partial",
  failed: "Failed",
};

export const X_FORMAT_LABEL: Record<string, string> = {
  insight: "Insight",
  how_to: "How-to",
  question: "Question",
  observation: "Observation",
  myth: "Myth",
  thread: "Thread",
  behind_the_scenes: "Behind the scenes",
};

export const DISMISS_REASON_LABEL: Record<string, string> = {
  not_relevant: "Not relevant",
  already_answered: "Already answered well",
  too_promotional: "Too promotional",
  other: "Other",
};

export const TIME_WINDOW_LABEL: Record<string, string> = {
  hour: "Hour",
  day: "Day",
  week: "Week",
};

/** A compliance rule id as a human phrase: "missing_disclosure" -> "missing disclosure". */
export function ruleLabel(rule: string): string {
  return rule.replace(/_/g, " ");
}

/* ----------------------------------------------------- run result summary */

/**
 * The "Result" cell in run history, built from the pipeline's stats blob.
 * Reads like the designs: "10 found · 3 scored ≥ 70 · 3 drafted".
 */
export function runSummary(kind: string, stats: RunStats | null | undefined): string {
  if (!stats) return "—";
  const parts: string[] = [];

  if (kind === "reddit") {
    if (stats.fetched !== undefined) parts.push(`${stats.fetched} found`);
    if (stats.duplicates) parts.push(`${stats.duplicates} seen before`);
    if (stats.above_threshold !== undefined) {
      const threshold = stats.threshold !== undefined ? ` ≥ ${stats.threshold}` : "";
      parts.push(`${stats.above_threshold} scored${threshold}`);
    }
    if (stats.drafted !== undefined) parts.push(`${stats.drafted} drafted`);
  } else if (kind === "content") {
    if (stats.topics_proposed !== undefined) parts.push(`${stats.topics_proposed} topics`);
    if (stats.topics_duplicate) parts.push(`${stats.topics_duplicate} duplicate`);
    if (stats.drafted !== undefined) parts.push(`${stats.drafted} drafted`);
  } else if (kind === "x") {
    if (stats.planned !== undefined) parts.push(`${stats.planned} planned`);
    if (stats.drafted !== undefined) parts.push(`${stats.drafted} drafted`);
    if (stats.revised) parts.push(`${stats.revised} revised`);
    if (stats.over_limit) parts.push(`${stats.over_limit} over limit`);
  } else if (kind === "onboarding" || kind === "recrawl") {
    if (stats.pages_crawled !== undefined) parts.push(`${stats.pages_crawled} pages`);
    if (stats.pages_rendered) parts.push(`${stats.pages_rendered} rendered`);
    if (stats.pages_thin) parts.push(`${stats.pages_thin} thin`);
  }

  const warnings = stats.warnings?.length ?? 0;
  if (warnings) parts.push(plural(warnings, "warning"));

  return parts.length ? parts.join(" · ") : "—";
}

/* ---------------------------------------------------------------- schedule */

/** A run time as the project sees it, e.g. "Mon 19 Oct, 9:00am", in an IANA zone. */
export function formatInZone(iso: string, timeZone: string): string {
  const date = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  const time = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone })
    .format(date)
    .replace(/\s/g, "")
    .toLowerCase();
  return `${part("weekday")} ${part("day")} ${part("month")}, ${time}`;
}

/* ---------------------------------------------------------- repeat hint */

const WINDOW_LABEL = { hour: "last hour", day: "last day", week: "last week" } as const;

/** Why most results repeat: each run searches a window much longer than the gap since the last run. */
export function repeatHintText(hint: RepeatHint): string {
  const gap = hint.gap_hours === 1 ? "every hour" : `every ${hint.gap_hours} hours`;
  return (
    `Each run searches the ${WINDOW_LABEL[hint.time_window]} of posts but runs ${gap}, ` +
    "so most results will be posts already seen. A shorter time window or a less frequent schedule fixes that."
  );
}
