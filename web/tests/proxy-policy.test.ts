import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { config as proxyConfig } from "../proxy";

// Unit tests for the pure middleware routing policy (web/lib/proxy-policy.ts).
// The policy is deliberately decoupled from `next/server`, so it can be
// exercised here without booting the Next runtime. proxy.ts itself is a thin
// adapter that maps these decisions onto NextResponse.

import {
  CODEX_CALLBACK_API_PATH,
  CODEX_CALLBACK_PATH,
  HANDOFF_PATH,
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isAdminPagePath,
  isCodexCallbackPath,
  isRetiredPagePath,
  isWebSocketPath,
  tokenRole,
} from "../lib/proxy-policy";
import { prepareBackendForwardHeaders } from "../lib/backend-forward";

function makeToken(payload: Record<string, unknown>): string {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256" })}.${encode(payload)}.signature`;
}

test("isBackendPath matches /api and /ws paths only", () => {
  assert.equal(isBackendPath("/api/knowledge-bases"), true);
  assert.equal(isBackendPath("/ws/chat"), true);
  assert.equal(isBackendPath("/chat"), false);
  assert.equal(isBackendPath("/apidocs"), false); // no trailing slash → not backend
  assert.equal(isBackendPath("/logo.png"), false);
  assert.equal(isWebSocketPath("/ws"), true);
  assert.equal(isWebSocketPath("/ws/books"), true);
  assert.equal(isWebSocketPath("/ws-extra"), false);
});

test("large knowledge uploads bypass the buffering proxy", () => {
  const matches = (url: string) =>
    unstable_doesMiddlewareMatch({ config: proxyConfig, url });

  assert.equal(matches("http://localhost/api/knowledge-bases"), false);
  assert.equal(matches("http://localhost/api/knowledge-bases/list"), true);
  assert.equal(
    matches("http://localhost/api/knowledge-bases/my%20kb/upload"),
    false,
  );
  assert.equal(
    matches("http://localhost/api/knowledge-bases/my%20kb/files"),
    true,
  );
  assert.equal(matches("http://localhost/chat"), true);
});

test("backend proxy allows long-running agent requests", () => {
  const nextConfig = require(path.resolve(process.cwd(), "next.config.js")) as {
    experimental?: { proxyTimeout?: number };
  };
  assert.ok(
    (nextConfig.experimental?.proxyTimeout ?? 0) >= 30 * 60 * 1000,
    "proxyTimeout must accommodate long PageIndex and Co-Writer turns",
  );
});

test("isCodexCallbackPath matches only the exact public callback path", () => {
  assert.equal(CODEX_CALLBACK_PATH, "/auth/callback");
  assert.equal(CODEX_CALLBACK_API_PATH, "/api/auth/openai-codex/callback");
  assert.equal(isCodexCallbackPath("/auth/callback"), true);
  assert.equal(isCodexCallbackPath("/auth/callback/"), false);
  assert.equal(isCodexCallbackPath("/auth/callback/extra"), false);
  assert.equal(isCodexCallbackPath("/auth/callback-near"), false);
  assert.equal(isCodexCallbackPath("/Auth/callback"), false);
});

test("retired pages cannot fall through to colliding dynamic routes", () => {
  assert.equal(isRetiredPagePath("/partners/groups"), true);
  assert.equal(isRetiredPagePath("/partners/groups/new"), false);
  assert.equal(isRetiredPagePath("/partners/groups/group-1"), false);
  assert.equal(isRetiredPagePath("/partners/group-1"), false);
});

test("proxy rewrites the exact callback before backend routing and auth gating", () => {
  const source = readFileSync(path.resolve(process.cwd(), "proxy.ts"), "utf8");
  const callbackBranch = source.indexOf("if (isCodexCallbackPath(pathname))");
  const backendBranch = source.indexOf("if (isBackendPath(pathname))");
  const authGate = source.indexOf("if (!AUTH_ENABLED");

  assert.notEqual(callbackBranch, -1);
  assert.notEqual(backendBranch, -1);
  assert.notEqual(authGate, -1);
  assert.ok(callbackBranch < backendBranch);
  assert.ok(callbackBranch < authGate);
  assert.match(
    source,
    /NextResponse\.rewrite\(\s*new URL\(\s*CODEX_CALLBACK_API_PATH \+ search,\s*API_BASE_URL,?\s*\),?\s*\)/,
  );
});

test("isAuthExempt allows public static assets through the auth gate (issue #599)", () => {
  // The Next image optimizer re-fetches these over a cookie-less loopback; if
  // the gate blocked them the sidebar logo/banner would render broken.
  assert.equal(isAuthExempt("/logo.png"), true);
  assert.equal(isAuthExempt("/banner.png"), true);
  assert.equal(isAuthExempt("/logo_black.png"), true);
  assert.equal(isAuthExempt("/brand/color-logo.png"), true);
  assert.equal(isAuthExempt("/brand/color-word.png"), true);
  assert.equal(isAuthExempt("/brand/black-logo.png"), true);
  assert.equal(isAuthExempt("/brand/favicon-32x32.png"), true);
  assert.equal(isAuthExempt("/apple-touch-icon.png"), true);
  assert.equal(isAuthExempt("/provider-icons/openai.svg"), true);
  assert.equal(isAuthExempt("/pdfjs/wasm/openjpeg.wasm"), true);
});

test("isAuthExempt allows auth pages and Next internals", () => {
  assert.equal(isAuthExempt("/login"), true);
  assert.equal(isAuthExempt("/register"), true);
  assert.equal(isAuthExempt("/_next/data/build/chat.json"), true);
  assert.equal(isAuthExempt("/favicon-32x32.png"), true);
});

test("public handoff page is exempt without exposing protected route prefixes", () => {
  assert.equal(isAuthExempt(HANDOFF_PATH), true);
  assert.equal(isAuthExempt("/handoff/extra"), false);
  assert.equal(isAuthExempt("/handoff-lookalike"), false);
});

test("backend forwarding replaces client identity headers with frontend host", () => {
  const headers = prepareBackendForwardHeaders(
    new Headers({
      connection: "keep-alive, x-remove-me",
      cookie: "dt_token=session",
      forwarded: "for=1.2.3.4;host=attacker.example",
      host: "app.example",
      "x-forwarded-for": "1.2.3.4",
      "x-forwarded-host": "attacker.example",
      "x-forwarded-proto": "https",
      "x-real-ip": "1.2.3.4",
      "x-deeptutor-frontend-host": "attacker.example",
      "x-remove-me": "hop-by-hop",
    }),
  );

  assert.equal(headers.get("x-deeptutor-frontend-host"), "app.example");
  assert.equal(headers.get("cookie"), "dt_token=session");
  for (const name of [
    "connection",
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "x-remove-me",
  ]) {
    assert.equal(headers.has(name), false, name);
  }
});

test("backend forwarding does not invent a frontend host from the Next URL", () => {
  const headers = prepareBackendForwardHeaders(new Headers({
    "x-forwarded-host": "app.example",
    "x-deeptutor-frontend-host": "app.example",
  }));
  assert.equal(headers.has("x-deeptutor-frontend-host"), false);
});

test("backend forwarding preserves only a valid WebSocket upgrade on /ws", () => {
  const source = new Headers({
    connection: "keep-alive, Upgrade, x-remove-me",
    upgrade: "websocket",
    host: "app.example",
    "sec-websocket-key": "test-key",
    "x-forwarded-for": "1.2.3.4",
    "x-remove-me": "hop-by-hop",
  });
  const websocket = prepareBackendForwardHeaders(source, {
    allowWebSocketUpgrade: true,
  });
  assert.equal(websocket.get("connection"), "Upgrade");
  assert.equal(websocket.get("upgrade"), "websocket");
  assert.equal(websocket.get("sec-websocket-key"), "test-key");
  assert.equal(websocket.get("x-deeptutor-frontend-host"), "app.example");
  assert.equal(websocket.has("x-forwarded-for"), false);
  assert.equal(websocket.has("x-remove-me"), false);

  const http = prepareBackendForwardHeaders(source);
  assert.equal(http.has("connection"), false);
  assert.equal(http.has("upgrade"), false);

  const invalid = prepareBackendForwardHeaders(
    new Headers({ connection: "Upgrade", upgrade: "h2c" }),
    { allowWebSocketUpgrade: true },
  );
  assert.equal(invalid.has("connection"), false);
  assert.equal(invalid.has("upgrade"), false);
});

test("isAuthExempt does NOT exempt protected app routes", () => {
  assert.equal(isAuthExempt("/chat"), false);
  assert.equal(isAuthExempt("/dashboard"), false);
  assert.equal(isAuthExempt("/space/agents"), false);
  assert.equal(isAuthExempt("/knowledge-bases"), false);
});

test("classifyToken reports missing for absent or empty cookie", () => {
  const now = 1_000_000_000_000;
  assert.equal(classifyToken(undefined, now), "missing");
  assert.equal(classifyToken("", now), "missing");
});

test("classifyToken reports malformed for non-JWT shapes", () => {
  const now = 1_000_000_000_000;
  assert.equal(classifyToken("a.b", now), "malformed"); // 2 segments
  assert.equal(classifyToken("a.b.c.d", now), "malformed"); // 4 segments
  // Valid 3-segment shape but the payload is not JSON → malformed.
  const notJson = `h.${Buffer.from("not-json").toString("base64url")}.s`;
  assert.equal(classifyToken(notJson, now), "malformed");
});

test("classifyToken honors expiry and accepts unexpired / expiry-less tokens", () => {
  const now = 1_000_000_000_000; // ms
  const nowSec = now / 1000;
  assert.equal(classifyToken(makeToken({ exp: nowSec + 3600 }), now), "valid");
  assert.equal(classifyToken(makeToken({ exp: nowSec - 1 }), now), "expired");
  assert.equal(classifyToken(makeToken({}), now), "valid"); // no exp claim
});

// --- Admin surface protection (DECISIONS.md F-1) ---------------------------
//
// Before this gate existed, /admin/users was protected only by a `useEffect`
// inside the page that called `router.replace`. That runs *after* the document
// has been handed to the browser, so the shell of the admin page was served to
// anyone who asked for it. These tests pin the server-side decision.

test("isAdminPagePath covers the admin surface and nothing adjacent", () => {
  assert.equal(isAdminPagePath("/admin"), true);
  assert.equal(isAdminPagePath("/admin/users"), true);
  assert.equal(isAdminPagePath("/admin/settings/billing"), true);
  // Near-misses must not be gated: a prefix check that is too eager would
  // lock ordinary users out of an unrelated page.
  assert.equal(isAdminPagePath("/administrator"), false);
  assert.equal(isAdminPagePath("/admin-panel"), false);
  assert.equal(isAdminPagePath("/chat"), false);
  assert.equal(isAdminPagePath("/"), false);
});

test("tokenRole reads the role claim", () => {
  assert.equal(tokenRole(makeToken({ role: "admin" })), "admin");
  assert.equal(tokenRole(makeToken({ role: "student" })), "student");
  assert.equal(tokenRole(makeToken({ role: "teacher" })), "teacher");
});

test("tokenRole fails closed", () => {
  // Every one of these must deny, not allow: an unreadable token is not a
  // reason to hand out the admin shell.
  assert.equal(tokenRole(undefined), null);
  assert.equal(tokenRole(""), null);
  assert.equal(tokenRole("not-a-jwt"), null);
  assert.equal(tokenRole("a.b"), null);
  assert.equal(tokenRole(makeToken({})), null); // no role claim
  assert.equal(tokenRole(makeToken({ role: 42 })), null); // wrong type
  assert.equal(
    tokenRole(`h.${Buffer.from("not-json").toString("base64url")}.s`),
    null,
  );
});

test("a token whose payload claims admin is read as admin", () => {
  // Documents the deliberate design: the middleware does not verify the
  // signature. Authorisation of *data* happens on the backend for every API
  // call; this gate only decides whether to render the shell at all. If that
  // assumption ever changes, this test is where it should fail.
  const forged = makeToken({ role: "admin" });
  assert.equal(tokenRole(forged), "admin");
  assert.equal(classifyToken(forged, Date.now()), "valid");
});

test("the middleware consults the admin gate before serving a page", () => {
  // The node harness runs compiled output under dist/node-tests, so walk up to
  // the real source tree rather than resolving relative to __dirname.
  let webRoot = __dirname;
  while (!existsSync(path.join(webRoot, "proxy.ts"))) {
    const parent = path.dirname(webRoot);
    if (parent === webRoot) throw new Error("could not locate web root");
    webRoot = parent;
  }
  const source = readFileSync(path.join(webRoot, "proxy.ts"), "utf-8");
  // Guard against the gate being dropped in a refactor: the call must exist and
  // must compare against the admin role.
  assert.match(source, /isAdminPagePath\(pathname\)/);
  assert.match(source, /tokenRole\(token\)\s*!==\s*"admin"/);
});

test("the admin sign-in page is reachable and does not loop", () => {
  // A sign-in page behind the gate it serves redirects to itself forever.
  // Both halves matter: the page must be exempt from the admin check AND from
  // the auth gate, or an unauthenticated visitor never sees a form.
  assert.equal(isAdminPagePath("/admin/login"), false);
  assert.equal(isAuthExempt("/admin/login"), true);
  assert.equal(isAuthExempt("/admin/users"), false);
});
