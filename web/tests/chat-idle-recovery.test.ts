import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  decideIdleTurnRecovery,
  resolveLoadedRunStatus,
} from "../lib/chat-idle-recovery";

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

/* ── Opening a conversation the backend never closed out ────────────────
   The backend marks a session `running` when a turn starts and clears it at
   the end, so a process that dies mid-turn leaves the row saying `running`
   forever. Believing it put the surface into "answering" with nothing to
   answer: Stop instead of Send, and no way back but a new conversation. */

const MINUTE = 60_000;
const NOW = Date.UTC(2026, 8, 2, 12, 0, 0);

test("a running turn touched moments ago is still running", () => {
  const now = NOW;
  assert.equal(
    resolveLoadedRunStatus("running", now - 5_000, now, 180_000),
    "running",
  );
});

test("a running row older than the idle window is not a live turn", () => {
  const now = NOW;
  assert.equal(
    resolveLoadedRunStatus("running", now - 4 * 24 * 60 * MINUTE, now, 180_000),
    "idle",
  );
});

test("only running is ever second-guessed", () => {
  const now = NOW;
  const ancient = now - 4 * 24 * 60 * MINUTE;
  for (const status of ["idle", "completed", "failed", "cancelled"] as const) {
    assert.equal(resolveLoadedRunStatus(status, ancient, now, 180_000), status);
  }
});

test("a missing timestamp leaves the server's word alone", () => {
  const now = NOW;
  assert.equal(resolveLoadedRunStatus("running", 0, now, 180_000), "running");
  assert.equal(
    resolveLoadedRunStatus("running", Number.NaN, now, 180_000),
    "running",
  );
});

test("the loader vets the stored status and skips subscribing to a stale turn", () => {
  const adapter = readFileSync("features/chat/ChatStateAdapter.tsx", "utf8");

  // The verdict has to reach both the state and the subscribe: opening a
  // socket for a turn we just judged dead would wait for events that can
  // never arrive.
  assert.match(adapter, /const loadedStatus = resolveLoadedRunStatus\(/);
  assert.match(adapter, /status: loadedStatus,/);
  assert.match(
    adapter,
    /if \(loadedStatus === "running" && \(activeTurn\?\.turn_id \|\| activeTurn\?\.id\)\)/,
  );

  // And a row with nothing in it is not a message. One such row used to be
  // enough to hide a surface's empty state while rendering an empty bubble.
  assert.match(adapter, /\(message\.attachments\?\.length \?\? 0\) > 0/);
});
