import test from "node:test";
import assert from "node:assert/strict";

import { searchAllSessions, searchSessions } from "../lib/session-api";

test("session search sends a literal bounded query and pagination", async () => {
  const original = globalThis.fetch;
  let capturedUrl = "";
  let capturedSignal: AbortSignal | null | undefined;
  (globalThis as { fetch: typeof fetch }).fetch = async (input, init) => {
    capturedUrl = String(input);
    capturedSignal = init?.signal;
    return new Response(
      JSON.stringify({ sessions: [], total: 0, limit: 25, offset: 50 }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  };
  const controller = new AbortController();

  try {
    const page = await searchSessions(
      "100%_literal",
      25,
      50,
      controller.signal,
    );
    const url = new URL(capturedUrl, "http://deeptutor.local");
    assert.equal(url.pathname, "/api/sessions/search");
    assert.equal(url.searchParams.get("q"), "100%_literal");
    assert.equal(url.searchParams.get("limit"), "25");
    assert.equal(url.searchParams.get("offset"), "50");
    assert.equal(capturedSignal, controller.signal);
    assert.deepEqual(page.sessions, []);
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

test("history search fetches every account-scoped result page", async () => {
  const original = globalThis.fetch;
  const urls: string[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (input) => {
    const url = new URL(String(input), "http://deeptutor.local");
    urls.push(url.pathname + url.search);
    const offset = Number(url.searchParams.get("offset"));
    const count = offset === 0 ? 100 : 50;
    return new Response(
      JSON.stringify({
        sessions: Array.from({ length: count }, (_, index) => ({
          id: `session-${offset + index}`,
          session_id: `session-${offset + index}`,
          title: "Chat",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
          last_message: "match",
          match_excerpt: "match",
        })),
        total: 150,
        limit: 100,
        offset,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const sessions = await searchAllSessions("Bayes", undefined, {
      allWorkspaces: true,
    });
    assert.equal(sessions.length, 150);
    assert.equal(urls.length, 2);
    assert.equal(
      new URL(urls[0], "http://deeptutor.local").searchParams.get(
        "all_workspaces",
      ),
      "true",
    );
    assert.equal(
      new URL(urls[1], "http://deeptutor.local").searchParams.get("offset"),
      "100",
    );
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});
