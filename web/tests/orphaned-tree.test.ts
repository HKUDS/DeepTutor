import test from "node:test";
import assert from "node:assert/strict";
import { buildVisiblePath } from "../lib/message-branches";
import type { MessageItem } from "../context/UnifiedChatContext";

// Issue #912: deleting a turn left descendants pointing at deleted rows, so
// buildVisiblePath found no root message and rendered a blank chat while
// markdown export still worked. The walk must fall back to the oldest orphan.
test("an orphaned tree (no root message) still renders from its oldest orphan", () => {
  const messages = [
    { id: 3, role: "user" as const, content: "q2", parentMessageId: 2 },
    { id: 4, role: "assistant" as const, content: "a2", parentMessageId: 3 },
  ];
  const visible = buildVisiblePath(messages as unknown as MessageItem[], {});
  assert.deepEqual(
    visible.messages.map((m) => m.content),
    ["q2", "a2"],
  );
});

test("a healthy root always wins over orphaned subtrees", () => {
  const messages = [
    { id: 1, role: "user" as const, content: "q1", parentMessageId: null },
    { id: 2, role: "assistant" as const, content: "a1", parentMessageId: 1 },
    // Orphaned tail from a later deleted turn (parent 99 doesn't exist).
    { id: 5, role: "user" as const, content: "q3", parentMessageId: 99 },
    { id: 6, role: "assistant" as const, content: "a3", parentMessageId: 5 },
  ];
  const visible = buildVisiblePath(messages as unknown as MessageItem[], {});
  assert.deepEqual(
    visible.messages.map((m) => m.content),
    ["q1", "a1"],
  );
});

test("empty message list still yields an empty path", () => {
  const visible = buildVisiblePath([], {});
  assert.deepEqual(visible.messages, []);
});
