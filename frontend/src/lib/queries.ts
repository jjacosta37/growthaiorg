/**
 * TanStack Query hooks, one per endpoint.
 *
 * Polling follows the plan's decision: /api/status/ every 2s while a run is active and
 * every 15s when idle. There is no SSE; progress comes from RunEvent rows.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api, type Paginated } from "./api";
import type {
  AgentRun,
  AgentSummary,
  AgentType,
  BlogTopic,
  BlogTopicStatus,
  ContentPolicy,
  ContextDoc,
  CrawledPage,
  DismissReason,
  DocKind,
  DocRevision,
  DraftContent,
  DraftDetail,
  DraftListItem,
  DraftStatus,
  InboxCounts,
  Nudge,
  PolicyPack,
  Project,
  RunEvent,
  SkippedPost,
  StatsPayload,
  StatusPayload,
  User,
} from "./types";
import { isRunActive } from "./types";

export const ACTIVE_POLL_MS = 2_000;
export const IDLE_POLL_MS = 15_000;

export const keys = {
  me: ["me"] as const,
  project: ["project"] as const,
  status: ["status"] as const,
  agents: ["agents"] as const,
  agent: (type: AgentType) => ["agents", type] as const,
  agentRuns: (type: AgentType) => ["agents", type, "runs"] as const,
  skipped: (minScore?: number) => ["agents", "reddit", "skipped", minScore ?? null] as const,
  topics: (status?: BlogTopicStatus) => ["topics", status ?? "all"] as const,
  drafts: (filters: DraftFilters) => ["drafts", filters] as const,
  draft: (id: number) => ["drafts", id] as const,
  counts: ["inbox", "counts"] as const,
  run: (id: number) => ["runs", id] as const,
  runEvents: (id: number) => ["runs", id, "events"] as const,
  docs: ["context", "docs"] as const,
  doc: (kind: DocKind) => ["context", "docs", kind] as const,
  revisions: (kind: DocKind) => ["context", "docs", kind, "revisions"] as const,
  pages: ["context", "pages"] as const,
  policy: ["policy"] as const,
  packs: ["policy", "packs"] as const,
  stats: (weeks: number) => ["stats", weeks] as const,
};

/* ------------------------------------------------------------------- auth */

export function useMe(options?: Partial<UseQueryOptions<User | null>>) {
  return useQuery<User | null>({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api.get<User>("/auth/me/");
      } catch {
        return null; // 403 here means "not signed in", not an error to surface
      }
    },
    staleTime: 30_000,
    retry: false,
    ...options,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api.post<User>("/auth/login/", body),
    onSuccess: (user) => {
      // Django rotates the CSRF token on login; the cookie is re-read on the next call.
      qc.setQueryData(keys.me, user);
      void qc.invalidateQueries();
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout/"),
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(keys.me, null);
    },
  });
}

/* --------------------------------------------------------------- project */

export function useProject(enabled = true) {
  return useQuery({
    queryKey: keys.project,
    queryFn: () => api.get<Project>("/project/"),
    enabled,
    staleTime: 60_000,
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Project>) => api.patch<Project>("/project/", body),
    onSuccess: (project) => qc.setQueryData(keys.project, project),
  });
}

/* ---------------------------------------------------------------- status */

/** The sidebar poll. Speeds up on its own while anything is running. */
export function useStatus(enabled = true) {
  return useQuery({
    queryKey: keys.status,
    queryFn: () => api.get<StatusPayload>("/status/"),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data as StatusPayload | undefined;
      return data?.active.length ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });
}

/* ------------------------------------------------------------------ runs */

export function useRun(id: number | null, options?: { poll?: boolean }) {
  return useQuery({
    queryKey: keys.run(id ?? 0),
    queryFn: () => api.get<AgentRun>(`/runs/${id}/`),
    enabled: id !== null,
    refetchInterval: (query) => {
      if (options?.poll === false) return false;
      const run = query.state.data as AgentRun | undefined;
      return run && isRunActive(run.status) ? ACTIVE_POLL_MS : false;
    },
  });
}

/**
 * A run's event log, fetched incrementally.
 *
 * /api/runs/<id>/events/?after=<id> returns only what is new, so each poll appends
 * rather than refetching the whole log.
 */
export function useRunEvents(id: number | null, active: boolean) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: keys.runEvents(id ?? 0),
    enabled: id !== null,
    queryFn: async () => {
      const previous = qc.getQueryData<RunEvent[]>(keys.runEvents(id ?? 0)) ?? [];
      const after = previous.length ? previous[previous.length - 1]!.id : undefined;
      const fresh = await api.list<RunEvent>(`/runs/${id}/events/`, { after });
      return fresh.length ? [...previous, ...fresh] : previous;
    },
    refetchInterval: active ? ACTIVE_POLL_MS : false,
  });
}

/* ---------------------------------------------------------------- agents */

export function useAgents(enabled = true) {
  return useQuery({
    queryKey: keys.agents,
    queryFn: () => api.list<AgentSummary>("/agents/"),
    enabled,
    staleTime: 10_000,
  });
}

export function useAgent<T extends AgentType>(type: T) {
  return useQuery({
    queryKey: keys.agent(type),
    queryFn: () => api.get<AgentSummary<T>>(`/agents/${type}/`),
  });
}

export function useUpdateAgent<T extends AgentType>(type: T) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { enabled?: boolean; cron?: string; config?: unknown }) =>
      api.patch<AgentSummary<T>>(`/agents/${type}/`, body),
    onSuccess: (agent) => {
      qc.setQueryData(keys.agent(type), agent);
      void qc.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

export function useRunNow(type: AgentType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<AgentRun>(`/agents/${type}/run-now/`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.status });
      void qc.invalidateQueries({ queryKey: keys.agent(type) });
      void qc.invalidateQueries({ queryKey: keys.agentRuns(type) });
    },
  });
}

export function useAgentRuns(type: AgentType, limit = 20) {
  return useQuery({
    queryKey: keys.agentRuns(type),
    queryFn: () => api.page<AgentRun>(`/agents/${type}/runs/`, { limit }),
  });
}

export function useSkippedPosts(minScore?: number) {
  return useQuery({
    queryKey: keys.skipped(minScore),
    queryFn: () =>
      api.page<SkippedPost>("/agents/reddit/skipped/", { min_score: minScore, limit: 50 }),
  });
}

/* ---------------------------------------------------------------- topics */

export function useTopics(status?: BlogTopicStatus) {
  return useQuery({
    queryKey: keys.topics(status),
    queryFn: () => api.page<BlogTopic>("/agents/content/topics/", { status, limit: 50 }),
  });
}

export function useRequestTopic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      title: string;
      angle?: string;
      target_keywords?: string[];
      draft_now?: boolean;
    }) => api.post<{ topic: BlogTopic; run: AgentRun | null }>("/agents/content/topics/", body),
    onSuccess: () => invalidateTopics(qc),
  });
}

export function useDraftTopic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<AgentRun>(`/agents/content/topics/${id}/draft/`),
    onSuccess: () => {
      invalidateTopics(qc);
      void qc.invalidateQueries({ queryKey: keys.status });
    },
  });
}

export function useRejectTopic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<BlogTopic>(`/agents/content/topics/${id}/reject/`),
    onSuccess: () => invalidateTopics(qc),
  });
}

function invalidateTopics(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: ["topics"] });
}

/* ----------------------------------------------------------------- inbox */

export interface DraftFilters {
  agent?: AgentType | "all";
  status: DraftStatus;
  sort: "newest" | "score";
}

export function useDrafts(filters: DraftFilters) {
  return useQuery({
    queryKey: keys.drafts(filters),
    queryFn: () =>
      api.page<DraftListItem>("/drafts/", {
        // `status` must always be sent: the endpoint silently defaults to "new".
        status: filters.status,
        agent: filters.agent && filters.agent !== "all" ? filters.agent : undefined,
        sort: filters.sort,
        limit: 100,
      }),
    placeholderData: (previous) => previous,
  });
}

export function useDraft(id: number | null) {
  return useQuery({
    queryKey: keys.draft(id ?? 0),
    queryFn: () => api.get<DraftDetail>(`/drafts/${id}/`),
    enabled: id !== null,
  });
}

export function useInboxCounts(enabled = true) {
  return useQuery({
    queryKey: keys.counts,
    queryFn: () => api.get<InboxCounts>("/inbox/counts/"),
    enabled,
    staleTime: 5_000,
  });
}

/** Everything the inbox shows about a draft, after any action that changes one. */
export function invalidateDraft(qc: QueryClient, id: number) {
  void qc.invalidateQueries({ queryKey: keys.draft(id) });
  void qc.invalidateQueries({ queryKey: ["drafts"] });
  void qc.invalidateQueries({ queryKey: keys.counts });
  void qc.invalidateQueries({ queryKey: keys.agents });
}

export function useEditDraft(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: DraftContent) => api.post<DraftDetail>(`/drafts/${id}/edit/`, { content }),
    onSuccess: (draft) => {
      qc.setQueryData(keys.draft(id), draft);
      invalidateDraft(qc, id);
    },
  });
}

export function useRegenerateDraft(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { nudge?: Nudge; instruction?: string }) =>
      api.post<AgentRun>(`/drafts/${id}/regenerate/`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.status });
      invalidateDraft(qc, id);
    },
  });
}

export function useMarkPosted(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (posted_url?: string) =>
      api.post<DraftDetail>(`/drafts/${id}/mark-posted/`, { posted_url: posted_url ?? "" }),
    onSuccess: (draft) => {
      qc.setQueryData(keys.draft(id), draft);
      invalidateDraft(qc, id);
    },
  });
}

export function useDismissDraft(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { reason: DismissReason; note?: string }) =>
      api.post<DraftDetail>(`/drafts/${id}/dismiss/`, body),
    onSuccess: (draft) => {
      qc.setQueryData(keys.draft(id), draft);
      invalidateDraft(qc, id);
    },
  });
}

export function useRestoreDraft(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<DraftDetail>(`/drafts/${id}/restore/`),
    onSuccess: (draft) => {
      qc.setQueryData(keys.draft(id), draft);
      invalidateDraft(qc, id);
    },
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<void>(`/drafts/${id}/read/`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.counts });
      void qc.invalidateQueries({ queryKey: ["drafts"] });
    },
  });
}

/* --------------------------------------------------------------- context */

export function useContextDocs(enabled = true) {
  return useQuery({
    queryKey: keys.docs,
    queryFn: () => api.list<ContextDoc>("/context/docs/"),
    enabled,
  });
}

export function useUpdateDoc(kind: DocKind) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content_md: string) =>
      api.patch<ContextDoc>(`/context/docs/${kind}/`, { content_md }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.docs });
      void qc.invalidateQueries({ queryKey: keys.revisions(kind) });
    },
  });
}

export function useRegenerateDoc(kind: DocKind) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<AgentRun>(`/context/docs/${kind}/regenerate/`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.status }),
  });
}

export function useRevisions(kind: DocKind, enabled: boolean) {
  return useQuery({
    queryKey: keys.revisions(kind),
    queryFn: () => api.list<DocRevision>(`/context/docs/${kind}/revisions/`),
    enabled,
  });
}

export function useCrawledPages(enabled = true) {
  return useQuery({
    queryKey: keys.pages,
    queryFn: () => api.list<CrawledPage>("/context/pages/"),
    enabled,
  });
}

export function useRecrawl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { overwrite_edited?: boolean; max_pages?: number }) =>
      api.post<AgentRun>("/context/recrawl/", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.status }),
  });
}

export function useStartOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { website_url: string; name?: string; max_pages?: number }) =>
      api.post<AgentRun>("/onboarding/start/", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.status }),
  });
}

/* ---------------------------------------------------------------- policy */

export function usePolicy(enabled = true) {
  return useQuery({
    queryKey: keys.policy,
    queryFn: () => api.get<ContentPolicy>("/policy/"),
    enabled,
  });
}

export function usePolicyPacks(enabled = true) {
  return useQuery({
    queryKey: keys.packs,
    queryFn: () => api.list<PolicyPack>("/policy/packs/"),
    enabled,
    staleTime: Infinity, // packs are static YAML on the server
  });
}

export function useUpdatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<ContentPolicy>) => api.patch<ContentPolicy>("/policy/", body),
    onSuccess: (policy) => qc.setQueryData(keys.policy, policy),
  });
}

export function useApplyPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pack: string) => api.post<ContentPolicy>("/policy/apply-pack/", { pack }),
    onSuccess: (policy) => {
      qc.setQueryData(keys.policy, policy);
      void qc.invalidateQueries({ queryKey: keys.docs });
    },
  });
}

/* ----------------------------------------------------------------- stats */

export function useStats(weeks: number) {
  return useQuery({
    queryKey: keys.stats(weeks),
    queryFn: () => api.get<StatsPayload>("/stats/", { weeks }),
    placeholderData: (previous) => previous,
  });
}

export type { Paginated };
