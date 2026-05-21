// API configuration and utility functions

// The Docker image and the `deeptutor start` launcher both build the Next.js
// bundle with this literal placeholder and substitute it at container/process
// start. If a deployment serves bundles where the substitution silently
// failed (read-only fs, missing tool, etc.), every API call would target a
// broken URL and the Settings page would render blank with no clue why.
// Treating the placeholder as "not configured" surfaces the failure mode
// instead of letting fetches die quietly.
//
// NOTE: The startup `sed` replaces `__NEXT_PUBLIC_API_BASE_PLACEHOLDER__` in
// every JS file. We must NOT keep a matching sentinel constant here, because
// sed would replace it too, making the validation check always fail.
// Instead, we detect the un-substituted state by checking for the distinctive
// prefix `__NEXT_PUBLIC_` which no valid URL would contain.

// Get API base URL injected by the launcher from data/user/settings/system.json.
// We deliberately do NOT throw at module-load time: the Docker build embeds the
// literal placeholder and Next.js evaluates this module during static export,
// which would fail every prerendered page. The runtime check in resolveBase()
// still surfaces missing/placeholder values on the first actual call.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE ?? "";

function assertApiBaseConfigured(value: string): string {
  const isPlaceholder = value.startsWith && value.startsWith("__NEXT_PUBLIC_");
  if (!value || isPlaceholder) {
    if (typeof window !== "undefined") {
      console.error(
        isPlaceholder
          ? "NEXT_PUBLIC_API_BASE placeholder was not substituted at startup."
          : "NEXT_PUBLIC_API_BASE is not set.",
      );
      console.error(
        "Please configure data/user/settings/system.json and restart the application.",
      );
    }
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not configured. Please update data/user/settings/system.json and restart.",
    );
  }
  return value;
}

// Hostnames that always refer to the local machine. When the build-time base
// URL points to one of these, but the page is opened from a non-local origin,
// we rewrite the hostname so requests reach the actual server.
const LOOPBACK_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  "[::1]",
]);

let warnedAboutHostSwap = false;

function isLoopbackHost(host: string): boolean {
  return LOOPBACK_HOSTS.has(host.toLowerCase());
}

/**
 * Resolve the effective API base URL at runtime.
 *
 * NEXT_PUBLIC_API_BASE is a build-time constant that is typically set to
 * http://localhost:<port>.  When another machine on the LAN opens the app that
 * constant still points at "localhost", which the remote browser resolves to
 * its *own* loopback address instead of the server.  We detect this situation
 * and swap the hostname for window.location.hostname so the request reaches
 * the actual server regardless of which machine opened the page.
 *
 * The full path/search is preserved (so deployments behind a reverse proxy
 * like `http://localhost:8001/api` continue to work after the rewrite).
 */
export function resolveBase(): string {
  const base = assertApiBaseConfigured(API_BASE_URL);
  if (typeof window === "undefined") return base;
  try {
    const url = new URL(base);
    const clientHost = window.location.hostname;
    if (isLoopbackHost(url.hostname) && !isLoopbackHost(clientHost)) {
      url.hostname = clientHost;
      if (!warnedAboutHostSwap) {
        warnedAboutHostSwap = true;
        console.warn(
          `[api] NEXT_PUBLIC_API_BASE points to "${base}" but the page is served from "${clientHost}"; ` +
            `routing API/WebSocket calls to "${url.toString()}" instead.`,
        );
      }
      // Use href (full URL) instead of origin so we keep any path/search.
      return url.toString().replace(/\/+$/, "");
    }
  } catch {
    // base is not a valid absolute URL – return as-is
  }
  return base;
}

/**
 * Construct a full API URL from a path
 * @param path - API path (e.g., '/api/v1/knowledge/list')
 * @returns Full URL (e.g., 'http://localhost:8001/api/v1/knowledge/list')
 */
export function apiUrl(path: string): string {
  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Remove trailing slash from base URL if present
  const base = resolveBase();
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}

/**
 * Construct a WebSocket URL from a path
 * @param path - WebSocket path (e.g., '/api/v1/solve')
 * @returns WebSocket URL (e.g., 'ws://localhost:8001/api/v1/ws')
 */
export function wsUrl(path: string): string {
  // Security Hardening: Convert http to ws and https to wss.
  // In production environments (where API_BASE_URL starts with https), this ensures secure websockets.
  const base = resolveBase()
    .replace(/^http:/, "ws:")
    .replace(/^https:/, "wss:");

  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Remove trailing slash from base URL if present
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

/**
 * Authenticated fetch wrapper. Behaves identically to `fetch` but automatically
 * redirects to /login when the backend returns 401 (expired / invalid token).
 */
export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const res = await fetch(input, { credentials: "include", ...init });

  if (res.status === 401 && AUTH_ENABLED && typeof window !== "undefined") {
    const next = encodeURIComponent(window.location.pathname);
    window.location.href = `/login?next=${next}`;
    return new Promise(() => {});
  }

  return res;
}
