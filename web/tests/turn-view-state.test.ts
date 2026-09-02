import assert from "node:assert/strict";
import test from "node:test";

import {
  turnPrimaryAction,
  turnStateMessageKey,
  turnViewState,
} from "../features/chat/model/turn-state";

test("server turn states map to complete user-facing lifecycle states", () => {
  const table = [
    [{ status: "queued" }, "queued", "cancel"],
    [{ status: "running" }, "running", "cancel"],
    [{ status: "waiting_input" }, "waiting_input", "answer"],
    [
      { queryState: "recovering", status: "running" },
      "recovering",
      "reconnect",
    ],
    [{ status: "completed" }, "completed", "none"],
    [{ status: "cancelled" }, "cancelled", "none"],
    [{ status: "running", cancellationRequested: true }, "cancelling", "none"],
  ] as const;

  for (const [input, expectedState, expectedAction] of table) {
    const state = turnViewState(input);
    assert.equal(state.kind, expectedState);
    assert.equal(turnPrimaryAction(state), expectedAction);
    assert.equal(
      turnStateMessageKey(state),
      `chat.turn.status.${expectedState}`,
    );
  }
});

test("transport loss recovers live turns but does not fabricate work", () => {
  assert.equal(
    turnViewState({ status: "running", transport: "offline" }).kind,
    "recovering",
  );
  assert.equal(turnViewState({ transport: "connecting" }).kind, "connecting");
  assert.equal(turnViewState({ transport: "offline" }).kind, "idle");
});

test("worker loss is retryable while provider rejection stays terminal", () => {
  const workerLost = turnViewState({
    status: "failed",
    errorCode: "worker_lost",
    errorMessage: "Owner exited",
  });
  assert.equal(workerLost.kind, "retryable_failure");
  assert.equal(turnPrimaryAction(workerLost), "regenerate");

  const rejected = turnViewState({
    status: "failed",
    errorCode: "rejected",
    retryable: false,
  });
  assert.equal(rejected.kind, "terminal_failure");
  assert.equal(turnPrimaryAction(rejected), "details");
});

test("arbitrary status strings never become view states", () => {
  assert.equal(turnViewState({ status: "probably_running" }).kind, "idle");
});
