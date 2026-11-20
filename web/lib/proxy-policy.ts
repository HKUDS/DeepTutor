// Pure request-routing policy for the Next.js middleware (web/proxy.ts).
//
// This module deliberately carries NO dependency on `next/server`: it answers
// "what should happen to this request?" as plain, side-effect-free functions,
// while proxy.ts stays a thin adapter that turns those answers into
// NextResponse objects. Keeping the policy pure means the routing/auth rules
// can be unit-tested in the node harness without booting the Next runtime.

export const LOGIN_PATH = "/login";
export const ADMIN_LOGIN_PATH = "/admin/login";
export const HANDOFF_PATH = "/handoff";
export const COOKIE_NAME = "dt_token";
export const CODEX_CALLBACK_PATH = "/auth/callback";
export const CODEX_CALLBACK_API_PATH = "/api/auth/openai-codex/callback";
const RETIRED_PAGE_PATHS = new Set(["/partners/groups"]);

export function isCodexCallbackPath(pathname: string): boolean {
  return pathname === CODEX_CALLBACK_PATH;
}

/** Exact retired pages that would otherwise collide with a dynamic route. */
export function isRetiredPagePath(pathname: string): boolean {
  return RETIRED_PAGE_PATHS.has(pathname);
}

// Paths whose responses come from the backend, not the Next app. The middleware
// rewrites these to DEEPTUTOR_API_BASE_URL so the browser can use frontend-
// relative URLs (e.g. `:3782/api/...` or `.../ws`) and let the rewrite
// bridge the origin gap.
export function isBackendPath(pathname: string): boolean {
  return (
    pathname.startsWith("/api/") ||
    isWebSocketPath(pathname) ||
    pathname.startsWith("/files/")
  );
}

export function isWebSocketPath(pathname: string): boolean {
  return pathname === "/ws" || pathname.startsWith("/ws/");
}

// Static assets served straight out of `web/public` (logos, favicons, fonts,
// provider icons, …). These must bypass the auth gate even in multi-user mode:
// the Next image optimizer re-fetches a referenced public image over a
// server-side loopback request that carries NO auth cookie, so gating the path
// bounces that fetch to /login and the `<Image>` renders as a broken icon
// (issue #599 — broken logo/banner after login). Public assets are
// non-sensitive by design, so allowing them through is safe.
const STATIC_ASSET =
  /\.(?:png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|txt|json|map|css|js|wasm)$/i;

// Paths the auth gate must never block: the auth pages themselves, Next.js
// internals, and public static assets (see STATIC_ASSET above).
export function isAuthExempt(pathname: string): boolean {
  return (
    pathname.startsWith(LOGIN_PATH) ||
    pathname.startsWith(ADMIN_LOGIN_PATH) ||
    pathname.startsWith("/register") ||
    pathname === HANDOFF_PATH ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    STATIC_ASSET.test(pathname)
  );
}

export type TokenState = "missing" | "malformed" | "expired" | "valid";

/**
 * Paths that only an administrator may open.
 *
 * `DECISIONS.md` F-1 requires the admin surface to be protected *server-side*,
 * not just by a `useEffect` that calls `router.replace`. A browser guard is a
 * navigation convenience: it runs after the document has already been handed
 * over, so anyone who blocks JavaScript, or simply requests the HTML directly,
 * never reaches it. This list is what the middleware consults.
 */
export function isAdminPagePath(pathname: string): boolean {
  // The admin sign-in page itself is not protected: requiring a session to
  // reach a sign-in form would redirect it to itself forever.
  if (pathname === ADMIN_LOGIN_PATH) return false;
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

/**
 * Read the `role` claim from a token **without verifying its signature**.
 *
 * This deliberately does not authenticate anything: the backend re-verifies
 * every API call, and the HTML this gate protects is a shell that renders
 * nothing until those calls succeed. What it stops is the useful attack —
 * fetching the admin page document at all — without adding a JWT library to
 * the Edge runtime for a decision the API already makes.
 *
 * Returns `null` when the claim is absent or the token is not a JWT, which
 * callers treat as "not an administrator" rather than "allow".
 */
export function tokenRole(token: string | undefined): string | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString("utf-8"),
    ) as { role?: unknown };
    return typeof payload.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

// Classify the auth cookie WITHOUT trusting its signature — the middleware is a
// cheap front-line gate, not the authority (the backend does real verification
// on every API call). `nowMs` is injected rather than read from the clock so
// the classifier stays pure and testable.
export function classifyToken(
  token: string | undefined,
  nowMs: number,
): TokenState {
  if (!token) return "missing";

  // Expect a JWT: header.payload.signature
  const parts = token.split(".");
  if (parts.length !== 3) return "malformed";

  try {
    const payload = JSON.parse(
      Buffer.from(parts[1], "base64url").toString("utf-8"),
    );
    if (payload.exp && nowMs >= payload.exp * 1000) return "expired";
  } catch {
    return "malformed";
  }

  return "valid";
}
