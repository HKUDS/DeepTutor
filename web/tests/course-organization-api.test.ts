import test from "node:test";
import assert from "node:assert/strict";

import { listAllSessions, updateSessionOrganization } from "../lib/session-api";
import { organizeSessionTree } from "../lib/session-organization";
import type { SessionSummary } from "../lib/session-api";

function session(
  id: string,
  parentSessionId = "",
  updatedAt = 1,
): SessionSummary {
  return {
    id,
    session_id: id,
    title: id,
    created_at: 1,
    updated_at: updatedAt,
    message_count: 0,
    last_message: "",
    preferences: { parent_session_id: parentSessionId },
  };
}

test("course organization fetches every session page", async () => {
  const original = globalThis.fetch;
  const offsets: number[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (input) => {
    const url = new URL(String(input), "http://deeptutor.local");
    const offset = Number(url.searchParams.get("offset") || 0);
    offsets.push(offset);
    const count = offset === 0 ? 200 : offset === 200 ? 3 : 0;
    return new Response(
      JSON.stringify({
        sessions: Array.from({ length: count }, (_, index) => ({
          id: `session-${offset + index}`,
          session_id: `session-${offset + index}`,
          title: "Chat",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
          last_message: "",
        })),
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const sessions = await listAllSessions({ force: true });
    assert.equal(sessions.length, 203);
    assert.deepEqual(offsets, [0, 200]);
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

test("course organization patch sends only the requested metadata", async () => {
  const original = globalThis.fetch;
  let capturedUrl = "";
  let capturedBody: unknown;
  (globalThis as { fetch: typeof fetch }).fetch = async (input, init) => {
    capturedUrl = String(input);
    capturedBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        session: {
          id: "child",
          session_id: "child",
          preferences: capturedBody,
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const session = await updateSessionOrganization("child", {
      course_id: "course-os",
      pinned: true,
    });
    assert.equal(capturedUrl, "/api/v1/sessions/child/organization");
    assert.deepEqual(capturedBody, { course_id: "course-os", pinned: true });
    assert.equal(session.preferences?.course_id, "course-os");
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

test("cyclic legacy parents remain renderable instead of recursing", () => {
  const organized = organizeSessionTree(
    [session("a", "b", 3), session("b", "a", 2), session("child", "a", 1)],
    true,
  );

  assert.deepEqual(
    organized.roots.map((row) => row.session_id),
    ["a", "b", "child"],
  );
  assert.equal(organized.childrenByParent.size, 0);
});
