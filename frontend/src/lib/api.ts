/**
 * The single door to the backend.
 *
 * Everything is same-origin under /api: in dev through the Vite proxy, in production
 * through the Render static-site rewrite. That keeps Django's SameSite=Lax session
 * cookie working without CORS.
 */

export const API_BASE = "/api";

/** DRF's LimitOffsetPagination envelope. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** A field name mapped to its messages, ready to render under an input. */
export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** True when the server refused because something else is already running. */
  get isConflict(): boolean {
    return this.status === 409;
  }

  /** The caller has no project yet — the app shows the create-project screen. */
  get isNoProject(): boolean {
    if (this.status !== 409) return false;
    const body = this.body;
    return (
      !!body &&
      typeof body === "object" &&
      (body as { code?: string }).code === "no_project"
    );
  }

  get isUnauthenticated(): boolean {
    return this.status === 401 || this.status === 403;
  }

  /**
   * The message to show a human. DRF puts one-line refusals in `detail`; that is what
   * 409s and 404s carry, and it is already written for display.
   */
  get detail(): string {
    const body = this.body;
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string") return d;
    }
    return this.message;
  }

  /** Field errors for a form, flattening both shapes the backend produces. */
  get fieldErrors(): FieldErrors {
    return toFieldErrors(this.body);
  }
}

interface PydanticIssue {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

function isPydanticIssue(value: unknown): value is PydanticIssue {
  return (
    !!value &&
    typeof value === "object" &&
    Array.isArray((value as PydanticIssue).loc) &&
    typeof (value as PydanticIssue).msg === "string"
  );
}

/**
 * Normalise the two validation shapes the backend returns into one map.
 *
 *   {"cron": ["Bad cron"]}                              -> {cron: ["Bad cron"]}
 *   {"config": [{loc: ["subreddits", 0], msg: "..."}]}  -> {"subreddits.0": ["..."]}
 *
 * The pydantic shape arrives nested under `config` or `content` (apps/core/errors.py),
 * so the wrapper key is dropped and `loc` becomes the path. An issue with an empty
 * `loc` keeps the wrapper key, since there is nothing more specific to point at.
 */
export function toFieldErrors(body: unknown): FieldErrors {
  if (!body || typeof body !== "object" || Array.isArray(body)) return {};

  const out: FieldErrors = {};
  const push = (key: string, message: string) => {
    (out[key] ??= []).push(message);
  };

  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (key === "detail") continue;

    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "string") {
          push(key, item);
        } else if (isPydanticIssue(item)) {
          const path = item.loc.join(".");
          push(path || key, item.msg);
        }
      }
    } else if (typeof value === "string") {
      push(key, value);
    }
  }

  return out;
}

/** Field errors as one line, for a form-level banner. */
export function summarise(errors: FieldErrors): string {
  return Object.entries(errors)
    .map(([field, messages]) =>
      field === "non_field_errors" ? messages.join(" ") : `${field}: ${messages.join(" ")}`,
    )
    .join(" · ");
}

/* --------------------------------------------------------------- project */

/**
 * The project the UI is currently showing, sent as X-Project-Id.
 *
 * The backend also keeps a selection in the session; the header wins, so two browser tabs
 * can sit on different projects. A project id the user doesn't own is ignored server-side
 * rather than refused.
 */
let projectId: number | null = null;

export function setProjectId(id: number | null): void {
  projectId = id;
}

export function getProjectId(): number | null {
  return projectId;
}

/* ------------------------------------------------------------------ CSRF */

let csrfToken: string | null = null;
let csrfInFlight: Promise<string> | null = null;

function cookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

/**
 * Django's CSRF token. The cookie is the source of truth — Django rotates it on login,
 * so a cached value can go stale. /api/auth/csrf/ both returns it and sets the cookie.
 */
export async function ensureCsrfToken(): Promise<string> {
  const fromCookie = cookie("csrftoken");
  if (fromCookie) {
    csrfToken = fromCookie;
    return fromCookie;
  }
  if (csrfToken) return csrfToken;

  csrfInFlight ??= fetch(`${API_BASE}/auth/csrf/`, { credentials: "same-origin" })
    .then(async (res) => {
      const body = (await res.json()) as { csrfToken: string };
      csrfToken = body.csrfToken;
      return csrfToken;
    })
    .finally(() => {
      csrfInFlight = null;
    });

  return csrfInFlight;
}

/** Forget the cached token. Call after login and logout, when Django rotates it. */
export function resetCsrfToken(): void {
  csrfToken = null;
}

/* ------------------------------------------------------------- the request */

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = path.startsWith("/api") ? path : `${API_BASE}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/** Listeners notified when the server says we are no longer signed in. */
type UnauthenticatedHandler = () => void;
let onUnauthenticated: UnauthenticatedHandler | null = null;

export function setUnauthenticatedHandler(handler: UnauthenticatedHandler | null): void {
  onUnauthenticated = handler;
}

/** Endpoints where a 403 is the answer, not a session problem. */
const AUTH_PROBE_PATHS = ["/auth/me/", "/auth/login/", "/auth/csrf/"];

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };

  if (projectId !== null) headers["X-Project-Id"] = String(projectId);

  if (!SAFE_METHODS.has(method)) {
    headers["X-CSRFToken"] = await ensureCsrfToken();
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const init: RequestInit = {
    method,
    headers,
    credentials: "same-origin",
  };
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  if (options.signal) init.signal = options.signal;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), init);
  } catch (cause) {
    // Network-level failure: the API is unreachable. Status 0 drives the offline banner.
    throw new ApiError(0, null, "Can't reach Luka");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const error = new ApiError(response.status, body);
    const isProbe = AUTH_PROBE_PATHS.some((p) => path.startsWith(p));
    if (error.isUnauthenticated && !isProbe) {
      resetCsrfToken();
      onUnauthenticated?.();
    }
    throw error;
  }

  return body as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    request<T>(path, { method: "GET", query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),

  /**
   * A list endpoint, whichever shape it uses. Several endpoints return a bare array
   * (agents, policy packs, context docs and pages, revisions, run events) while the
   * rest return DRF's envelope.
   */
  list: async <T>(
    path: string,
    query?: RequestOptions["query"],
    signal?: AbortSignal,
  ): Promise<T[]> => {
    const body = await request<T[] | Paginated<T>>(path, { method: "GET", query, signal });
    if (Array.isArray(body)) return body;
    return body?.results ?? [];
  },

  /** A paginated endpoint where the total matters (run history, skipped posts). */
  page: async <T>(
    path: string,
    query?: RequestOptions["query"],
    signal?: AbortSignal,
  ): Promise<Paginated<T>> => {
    const body = await request<T[] | Paginated<T>>(path, { method: "GET", query, signal });
    if (Array.isArray(body)) {
      return { count: body.length, next: null, previous: null, results: body };
    }
    return body;
  },
};
