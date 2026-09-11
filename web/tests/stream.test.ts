import test from "node:test";
import assert from "node:assert/strict";
import {
  collectNarrationCallIds,
  isNarrationMarker,
  recomputeAnswerContent,
} from "../lib/stream";
import type { StreamEvent } from "../features/chat/model/protocol";

function event(
  type: StreamEvent["type"],
  content: string,
  metadata: Record<string, unknown>,
): StreamEvent {
  return {
    type,
    source: "chat",
    stage: "responding",
    content,
    metadata,
    session_id: "session-1",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 0,
  };
}

test("ordinary narration is removed from answer content", () => {
  const events = [
    event("content", "Searching.", {
      call_id: "round-1",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-1",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
    }),
  ];

  assert.deepEqual([...collectNarrationCallIds(events)], ["round-1"]);
  assert.equal(isNarrationMarker(events[1]), true);
  assert.equal(recomputeAnswerContent(events), "");
});

test("clean prose surrounding a DSML call remains answer-visible", () => {
  const events = [
    event("content", "Great job! Choose the next topic.", {
      call_id: "round-dsml",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-dsml",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
      answer_visible: true,
    }),
  ];

  assert.deepEqual([...collectNarrationCallIds(events)], []);
  assert.equal(isNarrationMarker(events[1]), false);
  assert.equal(
    recomputeAnswerContent(events),
    "Great job! Choose the next topic.",
  );
});

test("token-limit continuation replays the exact visible answer", () => {
  const events = [
    event("content", "Part one. ", {
      call_id: "round-part-1",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-part-1",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
      answer_visible: true,
    }),
    event("content", "Part two.", {
      call_id: "round-part-2",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-part-2",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "finish",
    }),
  ];

  assert.equal(recomputeAnswerContent(events), "Part one. Part two.");
});

test("a finish that is rejected after streaming is withdrawn from the answer", () => {
  // A guarded surface (mastery, partner authoring) streams optimistically and
  // closes the round as `finish`. When its capability then rejects that finish,
  // the loop re-marks the same call_id as `narration`, and the already-visible
  // text has to come back out of the reply.
  const events = [
    event("content", "Which value is correct?\n\nA. one\nB. two\nC. three", {
      call_id: "round-1",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-1",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "finish",
    }),
    event("progress", "", {
      call_id: "round-1",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
      finish_rejected: true,
    }),
    event("content", "Let us try that on a card instead.", {
      call_id: "round-2",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-2",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "finish",
    }),
  ];

  assert.deepEqual([...collectNarrationCallIds(events)], ["round-1"]);
  assert.equal(
    recomputeAnswerContent(events),
    "Let us try that on a card instead.",
  );
});

test("an accepted finish keeps its text even after later rounds close", () => {
  const events = [
    event("content", "The derivative is 2x.", {
      call_id: "round-1",
      call_kind: "agent_loop_round",
    }),
    event("progress", "", {
      call_id: "round-1",
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "finish",
    }),
  ];

  assert.equal(collectNarrationCallIds(events).size, 0);
  assert.equal(recomputeAnswerContent(events), "The derivative is 2x.");
});
