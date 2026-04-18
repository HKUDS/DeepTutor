// API configuration and utility functions

// Get API base URL from environment variable.
// The launcher injects NEXT_PUBLIC_API_BASE from the canonical project-root `.env`.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE ||
  (() => {
    if (typeof window !== "undefined") {
      console.error("NEXT_PUBLIC_API_BASE is not set.");
      console.error(
        "Please configure NEXT_PUBLIC_API_BASE in your environment and restart the application.",
      );
      console.error("Run python scripts/start_tour.py to rebuild your local setup if needed.");
    }
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not configured. Please set it in your environment and restart.",
    );
  })();

/**
 * Resolve the effective API base URL at runtime.
 *
 * NEXT_PUBLIC_API_BASE is a build-time constant that is typically set to
 * http://localhost:<port>.  When another machine on the LAN opens the app that
 * constant still points at "localhost", which the remote browser resolves to
 * its *own* loopback address instead of the server.  We detect this situation
 * and swap the hostname for window.location.hostname so the request reaches
 * the actual server regardless of which machine opened the page.
 */
function resolveBase(): string {
  const base = API_BASE_URL;
  if (typeof window === "undefined") return base;
  try {
    const url = new URL(base);
    const isLoopback = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    const clientIsRemote =
      window.location.hostname !== "localhost" &&
      window.location.hostname !== "127.0.0.1";
    if (isLoopback && clientIsRemote) {
      url.hostname = window.location.hostname;
      return url.origin;
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
  const base = resolveBase().replace(/^http:/, "ws:").replace(/^https:/, "wss:");

  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Remove trailing slash from base URL if present
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}
