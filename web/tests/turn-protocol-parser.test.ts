import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCancelTurn,
  buildResumeTurn,
  buildSubmitUserReply,
  buildSubscribeTurn,
} from "../contracts/parse/turn-command";
import { parseTurnEvent } from "../contracts/parse/turn-event";

const eventTypes = [
  "stage_start",
  "stage_end",
  "thinking",
  "observation",
  "content",
  "tool_call",
  "tool_result",
  "progress",
  "sources",
  "result",
  "error",
  "session",
  "session_meta",
  "wait_for_input",
  "done",
] as const;

test("every v2 stream event kind crosses the validated boundary", () => {
  for (const [index, type] of eventTypes.entries()) {
    const parsed = parseTurnEvent(
      JSON.stringify({
        type,
        turn_id: "turn-1",
        seq: index,
        timestamp: 100 + index,
        content: "safe",
        metadata: { future_field: true },
        protocol_version: "2.0",
      }),
    );
    assert.equal(parsed.ok, true, type);
    if (parsed.ok) assert.equal(parsed.value.type, type);
  }
});

test("active turn information is validated and heartbeats are quarantined", () => {
  const active = parseTurnEvent({
    type: "active_turn_info",
    turn_id: "turn-1",
    status: "recovering",
    owner_id: "worker-2",
    protocol_version: "2.0",
  });
  assert.equal(active.ok, true);

  for (const heartbeat of ["", "heartbeat", '{"type":"ping"}']) {
    const parsed = parseTurnEvent(heartbeat);
    assert.deepEqual(parsed.ok ? null : parsed.reason, "heartbeat");
  }
  const pong = parseTurnEvent('{"type":"pong","protocol_version":"2.0"}');
  assert.equal(pong.ok, true);

  const acknowledgement = parseTurnEvent({
    type: "command_ack",
    command_id: "command-1",
    command_type: "user_input",
    accepted: true,
    turn_id: "turn-1",
    protocol_version: "2.0",
  });
  assert.equal(acknowledgement.ok, true);
});

test("invalid, incomplete, future, and version-mismatched frames are rejected", () => {
  const missing = parseTurnEvent({
    type: "content",
    turn_id: "turn-1",
    timestamp: 1,
    protocol_version: "2.0",
  });
  assert.deepEqual(missing.ok ? null : missing.reason, "invalid");

  const badSeq = parseTurnEvent({
    type: "content",
    turn_id: "turn-1",
    seq: -1,
    timestamp: 1,
    protocol_version: "2.0",
  });
  assert.deepEqual(badSeq.ok ? null : badSeq.reason, "invalid");

  const future = parseTurnEvent({
    type: "telepathy",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 1,
    protocol_version: "2.0",
  });
  assert.deepEqual(future.ok ? null : future.reason, "unsupported");

  const version = parseTurnEvent({
    type: "content",
    protocol_version: "3.0",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 1,
  });
  assert.deepEqual(version.ok ? null : version.reason, "unsupported");
});

test("protocol diagnostics never echo content, metadata, or credentials", () => {
  const parsed = parseTurnEvent({
    type: "future_event",
    content: "private prompt",
    metadata: { token: "secret-token" },
    password: "hunter2",
  });
  assert.equal(parsed.ok, false);
  if (parsed.ok) return;
  assert.doesNotMatch(
    parsed.diagnostic,
    /private prompt|secret-token|hunter2|content|metadata|password/,
  );
});

test("command builders enforce IDs, sequence bounds, replies, and v2 versioning", () => {
  assert.deepEqual(buildSubscribeTurn({ turnId: " turn-1 ", afterSeq: 7 }), {
    type: "subscribe_turn",
    turn_id: "turn-1",
    after_seq: 7,
    protocol_version: "2.0",
  });
  assert.equal(buildResumeTurn({ turnId: "turn-1", afterSeq: 9 }).seq, 9);
  assert.equal(buildCancelTurn("turn-1", "cancel-1").command_id, "cancel-1");
  assert.equal(
    buildSubmitUserReply({
      turnId: "turn-1",
      text: "yes",
      commandId: "reply-1",
    }).command_id,
    "reply-1",
  );

  assert.throws(
    () => buildSubscribeTurn({ turnId: " ", afterSeq: 0 }),
    /turn_id/,
  );
  assert.throws(
    () => buildSubscribeTurn({ turnId: "turn-1", afterSeq: 1.5 }),
    /after_seq/,
  );
  assert.throws(() => buildSubmitUserReply({ turnId: "turn-1" }), /requires/);
});
