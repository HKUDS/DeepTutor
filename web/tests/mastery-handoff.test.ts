import test from "node:test";
import assert from "node:assert/strict";

import {
  extractMasteryHandoffs,
  masteryHandoffFrom,
  masteryHandoffHref,
} from "../lib/mastery-handoff";

function toolResult(handoff: Record<string, unknown>, nested = true) {
  const payload = { mastery_handoff: handoff };
  return {
    type: "tool_result",
    metadata: nested ? { tool_metadata: payload } : payload,
  };
}

const OPEN = {
  kind: "open",
  path_id: "stats_101",
  path_name: "Intro Statistics",
  emoji: "📊",
  session_id: "sess_7",
  session_title: "Sampling distributions",
  session_messages: 12,
  session_updated_at: 1_760_000_000,
  session_awaiting: true,
  session_running: false,
  module_id: "m1",
  module_name: "Lesson 1 · Descriptive stats",
  opening_message: "Take me back through lesson 1 and quiz me",
  reason: "Three objectives there are due for review",
  due_reviews: 3,
  mastered: 9,
  objectives: 12,
};

test("a hand-off is read from the dispatcher's nested tool_metadata", () => {
  // The dispatcher nests a tool's own metadata under `tool_metadata`; reading
  // only the top level type-checks fine and silently finds nothing.
  const payload = masteryHandoffFrom(toolResult(OPEN));

  assert.equal(payload?.kind, "open");
  assert.equal(payload?.path_id, "stats_101");
  assert.equal(payload?.session_id, "sess_7");
  assert.equal(payload?.module_name, "Lesson 1 · Descriptive stats");
  assert.equal(payload?.session_awaiting, true);
  assert.equal(payload?.due_reviews, 3);
});

test("top-level metadata still works, for direct emitters", () => {
  const payload = masteryHandoffFrom(toolResult(OPEN, false));
  assert.equal(payload?.path_id, "stats_101");
});

test("a new-session hand-off needs no session id", () => {
  const payload = masteryHandoffFrom(
    toolResult({ kind: "new", path_id: "ml_path" }),
  );
  assert.equal(payload?.kind, "new");
  assert.equal(payload?.session_id, "");
  assert.equal(payload?.opening_message, "");
  assert.equal(payload?.session_awaiting, false);
});

test("an open hand-off without a session id is dropped", () => {
  // It would land on the topic's draft route and quietly start a *new*
  // conversation — the opposite of "take me back to where I was".
  assert.equal(
    masteryHandoffFrom(toolResult({ kind: "open", path_id: "ml_path" })),
    null,
  );
});

test("non-hand-off events and unknown kinds are ignored", () => {
  assert.equal(masteryHandoffFrom({ type: "text", metadata: {} }), null);
  assert.equal(
    masteryHandoffFrom(toolResult({ kind: "teleport", path_id: "x" })),
    null,
  );
  assert.equal(masteryHandoffFrom(toolResult({ kind: "new" })), null);
});

test("counts are floored at zero and non-numbers ignored", () => {
  const payload = masteryHandoffFrom(
    toolResult({
      kind: "new",
      path_id: "p",
      due_reviews: -2,
      mastered: "seven",
      objectives: 4.8,
    }),
  );
  assert.equal(payload?.due_reviews, 0);
  assert.equal(payload?.mastered, 0);
  assert.equal(payload?.objectives, 4);
});

test("one card per destination, but two destinations both survive", () => {
  const handoffs = extractMasteryHandoffs([
    toolResult(OPEN),
    toolResult(OPEN),
    toolResult({ kind: "new", path_id: "stats_101", module_id: "m2" }),
  ] as never);
  assert.equal(handoffs.length, 2);
  assert.deepEqual(
    handoffs.map((handoff) => handoff.kind),
    ["open", "new"],
  );
});

test("routes: open resumes a session, new lands on the draft route", () => {
  assert.equal(
    masteryHandoffHref({ ...OPEN, kind: "open" } as never),
    "/mastery/stats_101/sessions/sess_7",
  );
  assert.equal(
    masteryHandoffHref({ ...OPEN, kind: "new", session_id: "" } as never),
    "/mastery/stats_101/sessions",
  );
});

test("ids that reached us through a model are percent-encoded", () => {
  assert.equal(
    masteryHandoffHref({
      ...OPEN,
      path_id: "a/b",
      session_id: "c d",
    } as never),
    "/mastery/a%2Fb/sessions/c%20d",
  );
});
