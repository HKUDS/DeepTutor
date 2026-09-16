import test from "node:test";
import assert from "node:assert/strict";

import { searchSessions } from "../lib/session-api";

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
