// Pure request-routing policy for the Next.js middleware (web/proxy.ts).
//
// This module deliberately carries NO dependency on `next/server`: it answers
// "what should happen to this request?" as plain, side-effect-free functions,
// while proxy.ts stays a thin adapter that turns those answers into
// NextResponse objects. Keeping the policy pure means the routing/auth rules
// can be unit-tested in the node harness without booting the Next runtime.

export const LOGIN_PATH = "/login";
export const COOKIE_NAME = "dt_token";

// Paths whose responses come from the backend, not the Next app. The middleware
// rewrites these to DEEPTUTOR_API_BASE_URL so the browser can use frontend-
// relative URLs (e.g. `:3782/api/v1/...` or `.../ws`) and let the rewrite
// bridge the origin gap.
export function isBackendPath(pathname: string): boolean {
  return pathname.startsWith("/api/") || pathname.startsWith("/ws/");
}

// Static assets served straight out of `web/public` (logos, favicons, fonts,
// provider icons, …). These must bypass the auth gate even in multi-user mode:
// the Next image optimizer re-fetches a referenced public image over a
// server-side loopback request that carries NO auth cookie, so gating the path
// bounces that fetch to /login and the `<Image>` renders as a broken icon
// (issue #599 — broken logo/banner after login). Public assets are
// non-sensitive by design, so allowing them through is safe.
const STATIC_ASSET =
  /\.(?:png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|txt|json|map|css|js)$/i;

// Paths the auth gate must never block: the auth pages themselves, Next.js
// internals, and public static assets (see STATIC_ASSET above).
export function isAuthExempt(pathname: string): boolean {
  return (
    pathname.startsWith(LOGIN_PATH) ||
    pathname.startsWith("/register") ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    STATIC_ASSET.test(pathname)
  );
}

export type TokenState = "missing" | "malformed" | "expired" | "valid";

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
