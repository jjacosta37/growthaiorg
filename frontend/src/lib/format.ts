/** Display helpers. Pure functions, unit-tested in format.test.ts. */

import type { AgentType, DraftKind, RunStats, RunStatus } from "./types";

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

/**
 * Cron in plain words. The designs show a phrase with the raw expression behind an
 * "advanced" field, so this covers the shapes the schedule editor offers and falls
 * back to the expression itself for anything hand-written.
 */
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function clockTime(hour: number, minute: number): string {
  const suffix = hour < 12 ? "am" : "pm";
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return minute === 0 ? `${h}${suffix}` : `${h}:${String(minute).padStart(2, "0")}${suffix}`;
}

export function cronToPhrase(cron: string): string | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [min, hour, dom, mon, dow] = parts as [string, string, string, string, string];
  if (dom !== "*" || mon !== "*") return null;

  const minute = Number(min);
  if (!Number.isInteger(minute)) return null;

  // Every hour: "0 * * * *", and every N hours: "0 */4 * * *"
  if (dow === "*") {
    if (hour === "*") return "Every hour";
    const everyHours = /^\*\/(\d+)$/.exec(hour);
    if (everyHours) {
      const n = Number(everyHours[1]);
      return n === 1 ? "Every hour" : `Every ${n} hours`;
    }
  }

  const hourNum = Number(hour);
  if (!Number.isInteger(hourNum)) return null;
  const at = clockTime(hourNum, minute);

  if (dow === "*") return `Every day at ${at}`;
  if (dow === "1-5") return `Weekdays at ${at}`;
  if (dow === "0,6" || dow === "6,0") return `Weekends at ${at}`;

  const dowNum = Number(dow);
  if (Number.isInteger(dowNum) && dowNum >= 0 && dowNum <= 6) {
    return `${DAY_NAMES[dowNum]}s at ${at}`;
  }
  return null;
}

/** The phrase, or the raw expression when it isn't one of the common shapes. */
export function scheduleLabel(cron: string): string {
  return cronToPhrase(cron) ?? cron;
}

/** The options the plain-words schedule picker offers. */
export const SCHEDULE_PRESETS: { cron: string; label: string }[] = [
  { cron: "0 * * * *", label: "Every hour" },
  { cron: "0 */4 * * *", label: "Every 4 hours" },
  { cron: "0 */12 * * *", label: "Every 12 hours" },
  { cron: "0 9 * * *", label: "Every day at 9am" },
  { cron: "0 14 * * 1-5", label: "Weekdays at 2pm" },
  { cron: "0 9 * * 1", label: "Mondays at 9am" },
];

/** Rough validation so the advanced field can refuse obvious nonsense before saving. */
export function looksLikeCron(value: string): boolean {
  return value.trim().split(/\s+/).length === 5;
}
