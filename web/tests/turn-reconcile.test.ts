import test from "node:test";
import assert from "node:assert/strict";
import {
  reconcileTurnIds,
  type ReconcilableMessage,
} from "../lib/turn-reconcile";

interface Msg extends ReconcilableMessage {
  content: string;
}

const TURN = "turn_abc";

function optimisticTurn(): Msg[] {
  return [
    { id: 10, role: "user", content: "earlier", parentMessageId: null },
    {
      id: 11,
      role: "assistant",
      content: "earlier reply",
      parentMessageId: 10,
    },
    { id: -2000, role: "user", content: "question", parentMessageId: 11 },
    {
      id: -2001,
      role: "assistant",
      content: "streamed answer",
      parentMessageId: -2000,
      events: [{ turn_id: TURN }],
    },
  ];
}

test("swaps optimistic user+assistant ids and parent pointers", () => {
  const input = optimisticTurn();
  const result = reconcileTurnIds(
    input,
    {},
    {
      turnId: TURN,
      userMessageId: 12,
      assistantMessageId: 13,
    },
  );
  assert.equal(result.changed, true);
  const [, , user, assistant] = result.messages;
  assert.equal(user.id, 12);
  assert.equal(assistant.id, 13);
  assert.equal(assistant.parentMessageId, 12);
  // Untouched rows keep their object identity (no needless re-renders).
  assert.equal(result.messages[0], input[0]);
  assert.equal(result.messages[1], input[1]);
});

test("does not touch rows that already carry persisted ids", () => {
  const messages: Msg[] = [
    { id: 20, role: "user", content: "q", parentMessageId: null },
    {
      id: 21,
      role: "assistant",
      content: "a",
      parentMessageId: 20,
      events: [{ turn_id: TURN }],
    },
  ];
  const result = reconcileTurnIds(
    messages,
    {},
    {
      turnId: TURN,
      userMessageId: 99,
      assistantMessageId: 98,
    },
  );
  assert.equal(result.changed, false);
  assert.equal(result.messages, messages);
});

test("a stale done replay for an old turn cannot restamp a newer turn", () => {
  const messages: Msg[] = [
    { id: 30, role: "user", content: "old q", parentMessageId: null },
    {
      id: 31,
      role: "assistant",
      content: "old a",
      parentMessageId: 30,
      events: [{ turn_id: "turn_old" }],
    },
    { id: -3000, role: "user", content: "new q", parentMessageId: 31 },
    {
      id: -3001,
      role: "assistant",
      content: "new streaming a",
      parentMessageId: -3000,
      events: [{ turn_id: "turn_new" }],
    },
  ];
  // done replay for turn_old: its bubble already has real ids → no-op, and
  // crucially the newer optimistic bubble is left alone.
  const result = reconcileTurnIds(
    messages,
    {},
    {
      turnId: "turn_old",
      userMessageId: 77,
      assistantMessageId: 78,
    },
  );
  assert.equal(result.changed, false);
});

test("regenerate turns reconcile the assistant id only", () => {
  const messages: Msg[] = [
    { id: 40, role: "user", content: "q", parentMessageId: null },
    {
      id: -4001,
      role: "assistant",
      content: "regenerated",
      parentMessageId: 40,
      events: [{ turn_id: TURN }],
    },
  ];
  const result = reconcileTurnIds(
    messages,
    {},
    {
      turnId: TURN,
      userMessageId: null,
      assistantMessageId: 41,
    },
  );
  assert.equal(result.changed, true);
  assert.equal(result.messages[1].id, 41);
  assert.equal(result.messages[0].id, 40);
});

test("falls back to the last assistant bubble when turn id is missing", () => {
  const result = reconcileTurnIds(
    optimisticTurn(),
    {},
    {
      turnId: null,
      userMessageId: 12,
      assistantMessageId: 13,
    },
  );
  assert.equal(result.changed, true);
  assert.equal(result.messages[3].id, 13);
});

test("remaps selectedBranches keys and values that used optimistic ids", () => {
  const branches = { "11": -2000, "-2000": -2001 };
  const result = reconcileTurnIds(optimisticTurn(), branches, {
    turnId: TURN,
    userMessageId: 12,
    assistantMessageId: 13,
  });
  assert.deepEqual(result.selectedBranches, { "11": 12, "12": 13 });
});

test("returns original references when there is nothing to reconcile", () => {
  const messages = optimisticTurn();
  const branches = { "11": -2000 };
  const result = reconcileTurnIds(messages, branches, {
    turnId: "turn_unknown",
    userMessageId: 12,
    assistantMessageId: 13,
  });
  assert.equal(result.changed, false);
  assert.equal(result.messages, messages);
  assert.equal(result.selectedBranches, branches);
});
