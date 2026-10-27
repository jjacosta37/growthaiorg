/**
 * API types.
 *
 * `npm run gen:types` regenerates src/lib/schema.d.ts from /api/schema/, but several
 * views are declared `responses={200: dict}` in drf-spectacular and come out as
 * `object`. Those are written by hand here, against the serializers.
 */

/* ------------------------------------------------------------------ enums */

export const AGENT_TYPES = ["reddit", "content", "x"] as const;
export type AgentType = (typeof AGENT_TYPES)[number];

export type DraftKind = "reddit_comment" | "x_post" | "x_thread" | "blog_post";
export type DraftStatus = "new" | "posted" | "dismissed";
export type DismissReason = "not_relevant" | "already_answered" | "too_promotional" | "other" | "";
export type DraftVersionSource = "ai_initial" | "ai_regenerated" | "human_edit";
export type Nudge = "shorter" | "more_casual" | "no_mention" | "custom" | "";

export type RunKind =
  | "onboarding"
  | "recrawl"
  | "regenerate_doc"
  | "reddit"
  | "content"
  | "x"
  | "regenerate_draft"
  | "digest_feedback"
  | "publish_pr"
  | "suggest_reddit_targets";
export type RunTrigger = "scheduled" | "manual";
export type RunStatus =
  | "queued"
  | "running"
  | "waiting_batch"
  | "succeeded"
  | "partial"
  | "failed";
export type RunEventLevel = "info" | "success" | "warning" | "error";

export type DocKind =
  | "product"
  | "audience"
  | "brand_voice"
  | "competitors"
  | "content_strategy"
  | "compliance";
export type DocSource = "ai" | "human" | "template";
export type PolicySource = "default" | "suggested" | "user";
export type BlogTopicStatus = "proposed" | "drafted" | "rejected";

export const TERMINAL_RUN_STATUSES: RunStatus[] = ["succeeded", "partial", "failed"];
export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "running", "waiting_batch"];

export function isRunActive(status: RunStatus): boolean {
  return ACTIVE_RUN_STATUSES.includes(status);
}

/* ------------------------------------------------------------------- core */

export interface User {
  id: number;
  username: string;
  email: string;
}

export interface Competitor {
  name: string;
  url: string;
}

export interface Project {
  id: number;
  name: string;
  website_url: string;
  product_summary: string;
  competitors: Competitor[];
  onboarded_at: string | null;
}

/** A row in the project switcher. */
export interface ProjectSummary {
  id: number;
  name: string;
  website_url: string;
  onboarded_at: string | null;
  is_current: boolean;
  created_at: string;
}

/** /api/status/ — the sidebar poll. */
export interface StatusPayload {
  active: { id: number; kind: RunKind; status: RunStatus; current_step: string }[];
  message: string | null;
}

/* ------------------------------------------------------------------- runs */

export interface RunStats {
  warnings?: string[];
  errors?: string[];
  // crawl
  pages_discovered?: number;
  pages_crawled?: number;
  pages_skipped?: number;
  pages_thin?: number;
  pages_rendered?: number;
  // reddit
  fetched?: number;
  new_posts?: number;
  duplicates?: number;
  scored?: number;
  above_threshold?: number;
  threshold?: number;
  drafted?: number;
  // content
  topics_proposed?: number;
  topics_duplicate?: number;
  // x
  planned?: number;
  revised?: number;
  over_limit?: number;
  [key: string]: unknown;
}

export interface AgentRun {
  id: number;
  kind: RunKind;
  trigger: RunTrigger;
  status: RunStatus;
  current_step: string;
  params: Record<string, unknown>;
  stats: RunStats;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEvent {
  id: number;
  level: RunEventLevel;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

/* ----------------------------------------------------------------- agents */

export interface RedditConfig {
  subreddits: string[];
  keywords: string[];
  relevance_threshold: number;
  max_posts_per_run: number;
  time_window: "hour" | "day" | "week";
  include_nsfw: boolean;
  batch_scheduled_scoring: boolean;
  guidance: string;
}

export type OpportunityWeight = "off" | "low" | "medium" | "high";

export interface OpportunityWeights {
  volume: OpportunityWeight;
  ease: OpportunityWeight;
  reddit: OpportunityWeight;
}

export interface ContentConfig {
  topics_per_run: number;
  drafts_per_run: number;
  min_backlog: number;
  target_words: number;
  guidance: string;
  search_country: string;
  search_language: string;
  weights: OpportunityWeights;
}

/** The search markets keyword data can be looked up in, with each one's main language.
 *  Mirrors `MARKETS` in backend/providers/keywords/base.py, which validates them. */
export const SEARCH_MARKETS: { code: string; label: string; language: string }[] = [
  { code: "US", label: "United States", language: "en" },
  { code: "GB", label: "United Kingdom", language: "en" },
  { code: "CA", label: "Canada", language: "en" },
  { code: "AU", label: "Australia", language: "en" },
  { code: "NZ", label: "New Zealand", language: "en" },
  { code: "IE", label: "Ireland", language: "en" },
  { code: "IN", label: "India", language: "en" },
  { code: "SG", label: "Singapore", language: "en" },
  { code: "ZA", label: "South Africa", language: "en" },
  { code: "DE", label: "Germany", language: "de" },
  { code: "AT", label: "Austria", language: "de" },
  { code: "CH", label: "Switzerland", language: "de" },
  { code: "FR", label: "France", language: "fr" },
  { code: "BE", label: "Belgium", language: "nl" },
  { code: "NL", label: "Netherlands", language: "nl" },
  { code: "ES", label: "Spain", language: "es" },
  { code: "MX", label: "Mexico", language: "es" },
  { code: "IT", label: "Italy", language: "it" },
  { code: "PT", label: "Portugal", language: "pt" },
  { code: "BR", label: "Brazil", language: "pt" },
  { code: "PL", label: "Poland", language: "pl" },
  { code: "SE", label: "Sweden", language: "sv" },
  { code: "DK", label: "Denmark", language: "da" },
  { code: "FI", label: "Finland", language: "fi" },
  { code: "CZ", label: "Czechia", language: "cs" },
  { code: "UA", label: "Ukraine", language: "uk" },
  { code: "TR", label: "Turkey", language: "tr" },
  { code: "JP", label: "Japan", language: "ja" },
];

export const SEARCH_LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "de", label: "German" },
  { code: "fr", label: "French" },
  { code: "nl", label: "Dutch" },
  { code: "es", label: "Spanish" },
  { code: "it", label: "Italian" },
  { code: "pt", label: "Portuguese" },
  { code: "pl", label: "Polish" },
  { code: "sv", label: "Swedish" },
  { code: "da", label: "Danish" },
  { code: "fi", label: "Finnish" },
  { code: "cs", label: "Czech" },
  { code: "uk", label: "Ukrainian" },
  { code: "tr", label: "Turkish" },
  { code: "ja", label: "Japanese" },
];

export const X_FORMATS = [
  "insight",
  "how_to",
  "question",
  "observation",
  "myth",
  "thread",
  "behind_the_scenes",
] as const;
export type XFormat = (typeof X_FORMATS)[number];

export interface XConfig {
  posts_per_run: number;
  formats: XFormat[];
  max_thread_posts: number;
  char_limit: number;
  recent_window: number;
  guidance: string;
}

export type AgentConfigFor<T extends AgentType> = T extends "reddit"
  ? RedditConfig
  : T extends "content"
    ? ContentConfig
    : XConfig;

export interface DraftModelOption {
  key: string;
  label: string;
}

export type PublishMode = "manual" | "automatic";

/**
 * An agent schedule, in the project's local time. Times are "HH:MM" (24h) and days are
 * 0 = Sunday … 6 = Saturday. `custom` is a cron saved before the builder: it shows and keeps
 * running, but the API refuses to save one.
 */
export type Schedule =
  | { kind: "every_hours"; hours: 1 | 2 | 3 | 4 | 6 | 8 | 12; minute: number }
  | { kind: "daily"; times: string[] }
  | { kind: "weekdays"; days: number[]; times: string[] }
  | { kind: "weekly"; day: number; time: string }
  | { kind: "monthly"; day: number; time: string }
  | { kind: "custom"; cron: string };

export type ScheduleKind = Schedule["kind"];

/** /api/agents/schedule-preview/ */
export interface SchedulePreview {
  summary: string;
  next_runs: string[];
}

/** /api/agents/ and /api/agents/<type>/ */
export interface AgentSummary<T extends AgentType = AgentType> {
  agent_type: T;
  label: string;
  enabled: boolean;
  schedule: Schedule;
  /** Plain words naming the timezone, e.g. "Weekdays at 9:00am (Europe/Madrid)". */
  schedule_summary: string;
  /** The next 3 runs, ISO. */
  next_runs: string[];
  /** "too_frequent": a schedule saved before the hourly minimum; it runs until replaced. */
  schedule_warning: "too_frequent" | null;
  /** The project's timezone (UTC until one is chosen); shared by all its agents. */
  timezone: string;
  timezone_set: boolean;
  config: AgentConfigFor<T>;
  /** "automatic" (Content Agent only) also opens a GitHub pull request for each unflagged post. */
  publish_mode: PublishMode;
  /** Whether "automatic" can be chosen: the Content Agent with a ready GitHub connection. */
  automatic_available: boolean;
  /** Key of the model this agent drafts with; one of `draft_models`. */
  draft_model: string;
  /** The drafting models this project may pick, in display order. */
  draft_models: DraftModelOption[];
  last_run: AgentRun | null;
  last_error: string;
  next_run_at: string | null;
  /** Reddit only: the time window is over twice the gap between scheduled runs, so most results repeat. */
  repeat_hint: RepeatHint | null;
  ready: number;
}

export interface SkippedPost {
  id: number;
  subreddit: string;
  title: string;
  url: string;
  upvotes: number;
  num_comments: number;
  posted_at: string;
  score_status: "pending" | "scored" | "failed";
  relevance_score: number | null;
  relevance_reason: string;
  reply_worthwhile: boolean | null;
  score_error: string;
  fetched_at: string;
}

/* ------------------------------------------------------------------ inbox */

/** /api/inbox/counts/ */
export interface InboxCounts {
  unread: number;
  ready: Record<AgentType, number>;
  total_new: number;
  flagged: number;
}

export interface DraftListItem {
  id: number;
  channel: AgentType;
  kind: DraftKind;
  status: DraftStatus;
  title: string;
  score: number | null;
  subreddit: string | null;
  unread: boolean;
  flag_count: number;
  created_at: string;
}

export interface RedditCommentContent {
  body: string;
  /** Who the model thought it was writing for, from the poster's own words. */
  poster_read?: string;
}

export interface XPostContent {
  posts: string[];
  format: string;
  angle: string;
}

export interface BlogPostContent {
  title: string;
  meta_description: string;
  slug: string;
  keywords: string[];
  body_md: string;
}

export type DraftContent = RedditCommentContent | XPostContent | BlogPostContent;

export interface ComplianceFlag {
  rule: string;
  excerpt: string;
  explanation: string;
}

export interface DraftVersion {
  id: number;
  n: number;
  source: DraftVersionSource;
  content: DraftContent;
  nudge: Nudge;
  instruction: string;
  prompt_name: string;
  prompt_version: string;
  model: string;
  created_at: string;
}

export interface SourcePost {
  id: number;
  subreddit: string;
  title: string;
  body: string;
  url: string;
  author: string;
  upvotes: number;
  num_comments: number;
  posted_at: string;
  relevance_score: number | null;
  relevance_reason: string;
}

export interface BlogTopicRef {
  id: number;
  title: string;
  angle: string;
  target_keywords: string[];
  requested_by_user: boolean;
}

export interface DraftDetail extends DraftListItem {
  content: DraftContent;
  copy_text: string;
  open_url: string;
  source_post: SourcePost | null;
  blog_topic: BlogTopicRef | null;
  compliance_flags: ComplianceFlag[];
  versions: DraftVersion[];
  char_limit: number | null;
  posted_at: string | null;
  posted_url: string;
  dismiss_reason: DismissReason;
  dismiss_note: string;
  feedback: DraftFeedback[];
  /** Blog posts only, and only once GitHub is connected or a PR exists. */
  pull_request: DraftPullRequest | null;
}

/* ---------------------------------------------------------------- github */

export type PullRequestState = "held" | "pending" | "open" | "failed";

export interface DraftPullRequest {
  state: PullRequestState | null;
  number: number | null;
  url: string;
  repo: string;
  /** Why it was held, or why the last create or update failed. */
  note: string;
  /** A create or update is queued or running. */
  busy: boolean;
  can_create: boolean;
  /** The draft changed since it was last pushed to the PR. */
  needs_update: boolean;
  can_update: boolean;
}

export type GitHubConnectionStatus = "incomplete" | "ready" | "needs_reconnect";
export type FrontmatterField = "title" | "description" | "slug" | "keywords" | "date";

export interface ConstantField {
  key: string;
  value: string | number | boolean;
}

export interface GitHubConnection {
  status: GitHubConnectionStatus;
  account: string;
  repo: string;
  base_branch: string;
  base_branch_protected: boolean;
  folder: string;
  field_names: Record<FrontmatterField, string>;
  constant_fields: ConstantField[];
}

/** /api/github/ */
export interface GitHubStatus {
  /** This Luka server has a GitHub App configured. */
  available: boolean;
  connection: GitHubConnection | null;
  standard_fields: FrontmatterField[];
}

export interface GitHubRepo {
  full_name: string;
  default_branch: string;
}

export interface GitHubSettingsInput {
  repo: string;
  base_branch: string;
  folder: string;
  field_names: Partial<Record<FrontmatterField, string>>;
  constant_fields: ConstantField[];
}

export interface FrontmatterPreview {
  path: string;
  frontmatter: string;
  from_draft: number | null;
}

/* --------------------------------------------------------------- feedback */

export type FeedbackRating = "up" | "down" | "";
export type FeedbackSource = "explicit" | "instruction";

export interface DraftFeedback {
  id: number;
  source: FeedbackSource;
  rating: FeedbackRating;
  text: string;
  created_at: string;
  digested_at: string | null;
}

export interface FeedbackEntry extends DraftFeedback {
  draft: number | null;
  draft_title: string;
}

/** /api/agents/<type>/learnings/ */
export interface Learnings {
  writing: string;
  selection: string;
  source: "ai" | "human";
  updated_at: string;
  pending: number;
  digesting: boolean;
  entries: FeedbackEntry[];
}

/* ---------------------------------------------------------------- context */

export interface ContextDoc {
  kind: DocKind;
  title: string;
  content_md: string;
  source: DocSource;
  prompt_version: string;
  model: string;
  updated_at: string;
}

export interface DocRevision {
  id: number;
  content_md: string;
  source: DocSource;
  prompt_version: string;
  model: string;
  created_at: string;
}

export interface CrawledPage {
  id: number;
  url: string;
  title: string;
  chars: number;
  fetched_at: string;
}

/* ----------------------------------------------------------------- policy */

export interface PolicyRule {
  id: string;
  title: string;
  description: string;
}

export interface ContentPolicy {
  pack: string;
  pack_name: string;
  source: PolicySource;
  author_role: string;
  rules: PolicyRule[];
  disclosure: string;
  disclosure_preview: string;
  blog_disclaimer: string;
  updated_at: string;
}

export interface PolicyPack {
  id: string;
  name: string;
  description: string;
  rules: PolicyRule[];
  blog_disclaimer: string;
}

/* ----------------------------------------------------------------- topics */

export interface EvidencePost {
  id: number;
  subreddit: string;
  title: string;
  /** Always http(s), or "" when the stored URL wasn't safe to link. */
  url: string;
}

export type TopicSort = "opportunity" | "volume" | "difficulty" | "evidence" | "newest";

export interface BlogTopic {
  id: number;
  title: string;
  angle: string;
  target_keywords: string[];
  pillar: string;
  why: string;
  status: BlogTopicStatus;
  requested_by_user: boolean;
  draft_id: number | null;
  created_at: string;
  evidence: EvidencePost[];
  evidence_count: number;
  search_status: "pending" | "ready";
  primary_keyword: string;
  search_volume: number | null;
  keyword_difficulty: number | null;
  /** "US/en": the market the search data was looked up in. */
  search_market: string;
  low_volume: boolean;
}

/* ------------------------------------------------------------------ stats */

export interface AgentTotals {
  generated: number;
  posted: number;
  dismissed: number;
  pending: number;
  post_rate: number | null;
}

export interface SpendPayload {
  llm_weekly: number[];
  apify_weekly: number[];
  llm_total: number;
  apify_total: number;
  total: number;
  llm_by_agent: Record<string, number>;
  llm_by_model: Record<string, number>;
  apify_by_purpose: Record<string, number>;
  llm_calls: number;
  llm_failed_calls: number;
  cache_hit_rate: number | null;
}

/** /api/stats/ — every weekly series is index-aligned to `weeks`. */
export interface StatsPayload {
  weeks: string[];
  drafts: Record<AgentType, { generated: number[]; posted: number[]; dismissed: number[] }>;
  totals: Record<AgentType, AgentTotals>;
  dismiss_reasons: Record<AgentType, Record<string, number>>;
  spend: SpendPayload;
  reddit: { scanned: number[]; drafted: number[] };
}

/* ------------------------------------------------- reddit target suggestions */

export interface RepeatHint {
  time_window: "hour" | "day" | "week";
  window_hours: number;
  gap_hours: number;
}

export interface TargetSuggestion {
  id: number;
  value: string;
  reason: string;
}

/** "Suggest more" on the Reddit Agent page: pending suggestions and the latest run's state. */
export interface TargetSuggestions {
  suggesting: boolean;
  last_error: string;
  /** The latest "Suggest more" succeeded but had nothing new to offer. */
  nothing_new: boolean;
  subreddits: TargetSuggestion[];
  keywords: TargetSuggestion[];
  /** Slots left under the config's subreddit and keyword limits. */
  room: { subreddits: number; keywords: number };
  /** The config's limits on subreddits and keywords. */
  limits: { subreddits: number; keywords: number };
  /** Set by "add": how many values were appended to the config. */
  added?: number;
}
