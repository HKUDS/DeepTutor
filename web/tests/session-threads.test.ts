import test from "node:test";
import assert from "node:assert/strict";

import { groupThreadsByMessage } from "../lib/session-threads";
import type { SessionPreferences, SessionSummary } from "../lib/session-api";

function thread(
  id: string,
  preferences: SessionPreferences = {},
): SessionSummary {
  return {
    id,
    session_id: id,
    title: id,
    created_at: 1,
    updated_at: 1,
    message_count: 1,
    last_message: "",
    preferences,
  };
}

test("threads group under the message they were opened from", () => {
  const grouped = groupThreadsByMessage([
    thread("a", { tutor_source_message_id: 4 }),
    thread("b", { tutor_source_message_id: "4" }),
    thread("c", { tutor_source_message_id: 9 }),
  ]);

  assert.deepEqual(
    [...grouped.keys()].sort(),
    ["4", "9"],
  );
  assert.deepEqual(
    grouped.get("4")?.map((row) => row.session_id),
    ["a", "b"],
  );
});

test("threads without a quoted message or archived ones are not listed", () => {
  const grouped = groupThreadsByMessage([
    thread("bare", { tutor_scope: "conversation" }),
    thread("legacy", {}),
    thread("archived", { tutor_source_message_id: 4, archived: true }),
    thread("kept", { tutor_source_message_id: 4 }),
  ]);

  assert.deepEqual(
    grouped.get("4")?.map((row) => row.session_id),
    ["kept"],
  );
  assert.equal(grouped.size, 1);
});

test("an empty quoted id is treated as no attribution", () => {
  const grouped = groupThreadsByMessage([
    thread("empty", { tutor_source_message_id: "" }),
    thread("null", { tutor_source_message_id: null }),
  ]);

  assert.equal(grouped.size, 0);
});
