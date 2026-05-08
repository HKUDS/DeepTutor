import { NextRequest, NextResponse } from "next/server";

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";
const LOGIN_PATH = "/login";
const COOKIE_NAME = "dt_token";

export function middleware(req: NextRequest) {
  // Auth is disabled (default) — let everything through
  if (!AUTH_ENABLED) return NextResponse.next();

  const { pathname } = req.nextUrl;

  // Always allow auth pages and Next.js internals
  if (
    pathname.startsWith(LOGIN_PATH) ||
    pathname.startsWith("/register") ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon")
  ) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;

  // No token — redirect to login, preserving the intended destination
  if (!token) {
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = LOGIN_PATH;
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Run on all page routes, skip API and static assets
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
