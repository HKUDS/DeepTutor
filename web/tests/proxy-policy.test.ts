import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  classifyToken,
  isAuthExempt,
  isBackendPath,
  isCodexCallbackPath,
} from "../lib/proxy-policy";

function makeToken(payload: Record<string, unknown>): string {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256" })}.${encode(payload)}.signature`;
}

test("isBackendPath matches /api and /ws paths only", () => {
  assert.equal(isBackendPath("/api/v1/knowledge/list"), true);
  assert.equal(isBackendPath("/ws/chat"), true);
  assert.equal(isBackendPath("/home"), false);
  assert.equal(isBackendPath("/apidocs"), false); // no trailing slash → not backend
  assert.equal(isBackendPath("/logo.png"), false);
});

test("large knowledge uploads bypass the buffering proxy", () => {
  const matches = (url: string) =>
    unstable_doesMiddlewareMatch({ config: proxyConfig, url });

  assert.equal(matches("http://localhost/api/v1/knowledge/create"), false);
  assert.equal(
    matches("http://localhost/api/v1/knowledge/my%20kb/upload"),
    false,
  );
  assert.equal(matches("http://localhost/api/v1/knowledge/list"), true);
  assert.equal(matches("http://localhost/home"), true);
});

test("isCodexCallbackPath matches only the exact public callback path", () => {
  assert.equal(CODEX_CALLBACK_PATH, "/auth/callback");
  assert.equal(CODEX_CALLBACK_API_PATH, "/api/v1/auth/openai-codex/callback");
  assert.equal(isCodexCallbackPath("/auth/callback"), true);
  assert.equal(isCodexCallbackPath("/auth/callback/"), false);
  assert.equal(isCodexCallbackPath("/auth/callback/extra"), false);
  assert.equal(isCodexCallbackPath("/auth/callback-near"), false);
  assert.equal(isCodexCallbackPath("/Auth/callback"), false);
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
  assert.equal(isAuthExempt("/apple-touch-icon.png"), true);
  assert.equal(isAuthExempt("/provider-icons/openai.svg"), true);
});

test("isAuthExempt allows auth pages and Next internals", () => {
  assert.equal(isAuthExempt("/login"), true);
  assert.equal(isAuthExempt("/register"), true);
  assert.equal(isAuthExempt("/_next/data/build/home.json"), true);
  assert.equal(isAuthExempt("/favicon-32x32.png"), true);
});

test("isAuthExempt does NOT exempt protected app routes", () => {
  assert.equal(isAuthExempt("/home"), false);
  assert.equal(isAuthExempt("/dashboard"), false);
  assert.equal(isAuthExempt("/space/agents"), false);
  assert.equal(isAuthExempt("/knowledge"), false);
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
