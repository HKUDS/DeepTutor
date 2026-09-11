import assert from "node:assert/strict";
import test from "node:test";
import fixtures from "./fixtures/turn-lifecycle.json";
import type {
  ChatMessage,
  StreamEvent,
  StreamEventType,
} from "../features/chat/model/protocol";

const waitForInputKind: StreamEventType = "wait_for_input";

function asMessage(value: unknown): ChatMessage {
  return value as ChatMessage;
}

function asEvent(value: unknown): StreamEvent {
  return value as StreamEvent;
}

test("turn commands retain their public serialized shapes", () => {
  const commands = new Map(
    fixtures.commands.map(({ name, payload }) => [name, asMessage(payload)]),
  );

  assert.deepEqual(commands.get("start"), {
    type: "start_turn",
    content: "Explain replay-safe turns",
    session_id: null,
    capability: "chat",
  });
  assert.deepEqual(commands.get("subscribe"), {
    type: "subscribe_turn",
    turn_id: "turn-1",
    after_seq: 2,
  });
  assert.deepEqual(commands.get("resume"), {
    type: "resume_from",
    turn_id: "turn-1",
    seq: 2,
  });
  assert.equal(commands.get("regenerate")?.type, "regenerate");
  assert.deepEqual(commands.get("cancel"), {
    type: "cancel_turn",
    turn_id: "turn-1",
  });
  assert.deepEqual(commands.get("submit_user_reply"), {
    type: "submit_user_reply",
    turn_id: "turn-1",
    answers: [{ questionId: "scope", text: "Use the multi-worker path" }],
  });
});

test("the first event identifies the session and replay order is monotonic", () => {
  const events = fixtures.successfulEvents.map(asEvent);

  assert.equal(events[0].type, "session");
  assert.equal(events[0].session_id, "session-1");
  assert.equal(events[0].turn_id, "turn-1");
  assert.deepEqual(
    events.map((event) => event.seq),
    [1, 2, 3, 4, 5],
  );
  assert.equal(events[2].type, waitForInputKind);
});

test("done carries authoritative terminal metadata", () => {
  const done = asEvent(fixtures.successfulEvents.at(-1));

  assert.equal(done.type, "done");
  assert.deepEqual(done.metadata, {
    turn_terminal: true,
    status: "completed",
  });
});

test("error carries a stable code and retryability metadata", () => {
  const error = asEvent(fixtures.failedEvents.at(-1));

  assert.equal(error.type, "error");
  assert.deepEqual(error.metadata, {
    turn_terminal: true,
    status: "failed",
    error_code: "worker_lost",
    retryable: true,
  });
});
