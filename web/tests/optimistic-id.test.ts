import test from "node:test";
import assert from "node:assert/strict";
import {
  nextOptimisticId,
  resolvePersistedMessage,
} from "../lib/optimistic-id";
import { reconcileTurnIds } from "../lib/turn-reconcile";
import {
  buildVisiblePath,
  persistedBranchSelections,
  selectChildBranch,
  tipMessageId,
} from "../lib/message-branches";
import type { MessageItem } from "../features/chat/ChatStateAdapter";

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

// deleteTurn used to re-read stateRef after loadSession (same race as #739's
// edit path). Both mutations must trust the refresh snapshot's id.
test("deleteTurn-style resolution keeps working when the state ref is stale", async () => {
  const staleRef = [
    { id: -42, role: "user", content: "to delete", parentMessageId: 1 },
    { id: -43, role: "assistant", content: "reply", parentMessageId: -42 },
  ];
  const serverSnapshot = [
    { id: 201, role: "user", content: "to delete", parentMessageId: 1 },
    { id: 202, role: "assistant", content: "reply", parentMessageId: 201 },
  ];

  const target = await resolvePersistedMessage(
    staleRef,
    -42,
    "user",
    async () => serverSnapshot,
  );

  assert.equal(target?.id, 201);
  assert.equal(staleRef[0].id, -42);
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

test("a freshly edited sibling overrides the previously selected branch", () => {
  const messages = [
    { id: 10, role: "user" as const, content: "q1", parentMessageId: null },
    {
      id: 11,
      role: "assistant" as const,
      content: "a1",
      parentMessageId: 10,
    },
    {
      id: 12,
      role: "user" as const,
      content: "original q2",
      parentMessageId: 11,
    },
    {
      id: -20,
      role: "user" as const,
      content: "edited q2",
      parentMessageId: 11,
    },
  ];

  const selectedBranches = selectChildBranch({ "11": 12 }, 11, -20);
  const visible = buildVisiblePath(
    messages as unknown as MessageItem[],
    selectedBranches,
  );

  assert.deepEqual(
    visible.messages.map((message) => message.content),
    ["q1", "a1", "edited q2"],
  );
});

test("the edited branch and its reply survive optimistic id reconciliation", () => {
  const editedId = nextOptimisticId();
  const replyId = nextOptimisticId();
  const messages = [
    { id: 10, role: "user" as const, content: "q1", parentMessageId: null },
    {
      id: 11,
      role: "assistant" as const,
      content: "a1",
      parentMessageId: 10,
    },
    {
      id: 12,
      role: "user" as const,
      content: "original q2",
      parentMessageId: 11,
    },
    {
      id: editedId,
      role: "user" as const,
      content: "edited q2",
      parentMessageId: 11,
    },
    {
      id: replyId,
      role: "assistant" as const,
      content: "edited a2",
      parentMessageId: editedId,
      events: [{ turn_id: "turn_2" }],
    },
  ];

  const reconciled = reconcileTurnIds(
    messages as unknown as MessageItem[],
    selectChildBranch({}, 11, editedId),
    { turnId: "turn_2", userMessageId: 30, assistantMessageId: 31 },
  );
  const visible = buildVisiblePath(
    reconciled.messages,
    reconciled.selectedBranches,
  );

  assert.equal(reconciled.selectedBranches["11"], 30);
  assert.deepEqual(
    visible.messages.map((message) => message.content),
    ["q1", "a1", "edited q2", "edited a2"],
  );
});

test("persisted branch selections drop optimistic ids", () => {
  assert.deepEqual(
    persistedBranchSelections({ null: -42, "10": 11, "11": -99, "12": 13 }),
    { "10": 11, "12": 13 },
  );
});
