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
  | "regenerate_draft";
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
}

export interface ContentConfig {
  topics_per_run: number;
  drafts_per_run: number;
  min_backlog: number;
  target_words: number;
  guidance: string;
}

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

/** /api/agents/ and /api/agents/<type>/ */
export interface AgentSummary<T extends AgentType = AgentType> {
  agent_type: T;
  label: string;
  enabled: boolean;
  cron: string;
  config: AgentConfigFor<T>;
  publish_mode: "manual";
  last_run: AgentRun | null;
  last_error: string;
  next_run_at: string | null;
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
