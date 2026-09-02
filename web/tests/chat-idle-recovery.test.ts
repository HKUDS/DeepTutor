import test from "node:test";
import assert from "node:assert/strict";
import { decideIdleTurnRecovery } from "../lib/chat-idle-recovery";

test("an idle live turn is resumed instead of being marked failed", () => {
  assert.deepEqual(
    decideIdleTurnRecovery({
      isStreaming: true,
      hasPendingUserInput: false,
      activeTurnId: "turn_research",
      lastSeq: 42,
      updatedAt: 1_000,
      now: 181_001,
      idleTimeoutMs: 180_000,
    }),
    {
      kind: "resubscribe",
      message: {
        type: "resume_from",
        turn_id: "turn_research",
        seq: 42,
        protocol_version: "2.0",
      },
    },
  );
});

test("a paused ask-user turn is not touched by the idle watchdog", () => {
  assert.deepEqual(
    decideIdleTurnRecovery({
      isStreaming: true,
      hasPendingUserInput: true,
      activeTurnId: "turn_waiting",
      lastSeq: 7,
      updatedAt: 1_000,
      now: 999_999,
      idleTimeoutMs: 180_000,
    }),
    { kind: "none" },
  );
});

test("a stale stream without a server turn id requests reconciliation", () => {
  const decision = decideIdleTurnRecovery({
    isStreaming: true,
    hasPendingUserInput: false,
    activeTurnId: null,
    lastSeq: 0,
    updatedAt: 1_000,
    now: 181_001,
    idleTimeoutMs: 180_000,
  });

  assert.equal(decision.kind, "reconcile");
});
