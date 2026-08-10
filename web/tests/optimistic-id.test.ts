import test from "node:test";
import assert from "node:assert/strict";
import {
  nextOptimisticId,
  resolvePersistedMessage,
} from "../lib/optimistic-id";
import { reconcileTurnIds } from "../lib/turn-reconcile";
import { buildVisiblePath, tipMessageId } from "../lib/message-branches";
import type { MessageItem } from "../context/UnifiedChatContext";

test("optimistic ids are negative and strictly decreasing", () => {
  const ids = Array.from({ length: 50 }, () => nextOptimisticId());
  for (const id of ids) assert.ok(id < 0, `${id} must be negative`);
  for (let i = 1; i < ids.length; i++) {
    assert.ok(
      ids[i] < ids[i - 1],
      `${ids[i]} must be older-ranking than ${ids[i - 1]}`,
    );
  }
  assert.equal(new Set(ids).size, ids.length, "ids must be unique");
});

// Issue #739: loadSession dispatches the persisted snapshot, but stateRef is
// only updated after React commits. The first edit must use the snapshot that
// loadSession just returned instead of immediately reading the stale ref.
test("an optimistic message resolves from the returned refresh snapshot", async () => {
  const optimistic = [
    { id: -100, role: "user", content: "question", parentMessageId: 10 },
  ];
  const persisted = [
    { id: 11, role: "user", content: "question", parentMessageId: 10 },
  ];

  const resolved = await resolvePersistedMessage(
    optimistic,
    -100,
    "user",
    async () => persisted,
  );

  assert.equal(resolved?.id, 11);
  assert.equal(optimistic[0].id, -100, "the state ref can still be stale");
});

// Issue #698: the user row and the assistant placeholder are minted
// back-to-back (ADD_USER_MSG then STREAM_START). When they shared an id, the
// remap in reconcileTurnIds collapsed both onto the user's persisted id, so
// the next turn chained under the previous USER message and the reply
// vanished from the visible path until a session reload.
test("a turn's two optimistic rows reconcile to distinct persisted ids", () => {
  const userId = nextOptimisticId();
  const assistantId = nextOptimisticId();
  assert.notEqual(userId, assistantId);

  const messages = [
    { id: userId, role: "user" as const, content: "q1", parentMessageId: null },
    {
      id: assistantId,
      role: "assistant" as const,
      content: "a1",
      parentMessageId: userId,
      events: [{ turn_id: "turn_1" }],
    },
  ];
  const { messages: reconciled } = reconcileTurnIds(
    messages,
    {},
    { turnId: "turn_1", userMessageId: 166, assistantMessageId: 167 },
  );
  assert.deepEqual(
    reconciled.map((m) => [m.role, m.id, m.parentMessageId]),
    [
      ["user", 166, null],
      ["assistant", 167, 166],
    ],
  );

  // The follow-up message must chain under the assistant reply, not the
  // previous user message.
  const visible = buildVisiblePath(reconciled as unknown as MessageItem[], {});
  assert.equal(tipMessageId(visible.messages), 167);
});

test("the previous reply stays visible once the next turn is queued", () => {
  const messages = [
    { id: 166, role: "user" as const, content: "q1", parentMessageId: null },
    {
      id: 167,
      role: "assistant" as const,
      content: "a1",
      parentMessageId: 166,
    },
    {
      id: nextOptimisticId(),
      role: "user" as const,
      content: "q2",
      parentMessageId: 167,
    },
  ];
  const visible = buildVisiblePath(messages as unknown as MessageItem[], {});
  assert.deepEqual(
    visible.messages.map((m) => m.content),
    ["q1", "a1", "q2"],
  );
});
