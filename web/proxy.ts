import { NextRequest, NextResponse } from "next/server";
import { parseAuthEnabled } from "./lib/api";
import {
  COOKIE_NAME,
  LOGIN_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
} from "./lib/proxy-policy";

// Backend base URL for `/api/*` and `/ws/*` rewrites. The container entrypoint
// exports `DEEPTUTOR_API_BASE_URL` from `data/user/settings/system.json`
// (preferring `next_public_api_base`, then `next_public_api_base_external`,
// then `http://localhost:${BACKEND_PORT}`). In dev (`deeptutor start`) it
// defaults to `http://localhost:8001`.
const API_BASE_URL =
  process.env.DEEPTUTOR_API_BASE_URL ?? "http://localhost:8001";

const AUTH_ENABLED = parseAuthEnabled(process.env.DEEPTUTOR_AUTH_ENABLED);

// Redirect to the login page, preserving the intended destination in `next`.
// A present-but-invalid cookie is cleared so the browser stops resending it;
// when no cookie was sent there is nothing to clear.
function redirectToLogin(
  req: NextRequest,
  { clearCookie }: { clearCookie: boolean },
): NextResponse {
  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = LOGIN_PATH;
  loginUrl.searchParams.set("next", req.nextUrl.pathname);
  const response = NextResponse.redirect(loginUrl);
  if (clearCookie) response.cookies.delete(COOKIE_NAME);
  return response;
}

export function proxy(req: NextRequest): NextResponse {
  const { pathname, search } = req.nextUrl;

  // 1. Bridge the origin gap: forward backend-relative paths to the API server.
  //    This keeps the URL knowledge in one place (the entrypoint + system.json)
  //    rather than baked into the frontend bundle.
  if (isBackendPath(pathname)) {
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL));
  }

  // 2. Auth gate — multi-user mode only. Disabled by default, and never blocks
  //    auth pages, Next.js internals, or public static assets (see
  //    isAuthExempt: that exemption is what keeps the logo/banner images
  //    loading once login is enabled — issue #599).
  if (!AUTH_ENABLED || isAuthExempt(pathname)) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (classifyToken(token, Date.now()) !== "valid") {
    return redirectToLogin(req, { clearCookie: Boolean(token) });
  }

  return NextResponse.next();
}

export const config = {
  // Run on every request except Next.js internals and the favicon. The /api/*
  // and /ws/* paths are explicitly handled above (rewritten to the backend);
  // the browser's /_next/image optimizer requests are excluded here, while the
  // optimizer's loopback fetch for the source image (e.g. /logo.png) is let
  // through the auth gate by isAuthExempt.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
