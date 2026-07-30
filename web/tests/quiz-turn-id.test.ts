import test from "node:test";
import assert from "node:assert/strict";

import { extractQuizTurnId } from "../lib/quiz-types";

// Regression tests for issue #677: during streaming generation the final
// ``result`` event hasn't landed yet, but the quiz card still needs its turn
// identity so notebook lookups/writes stay scoped to this quiz instead of
// falling back to the previous quiz's session-wide state.

test("extractQuizTurnId reads the turn id from streamed events before result", () => {
  const events = [
    { type: "stage_start", turn_id: "turn_B" },
    {
      type: "content",
      turn_id: "turn_B",
      metadata: { call_kind: "quiz_question_emitted" },
    },
  ];
  assert.equal(extractQuizTurnId(events), "turn_B");
});

test("extractQuizTurnId prefers the result event's turn id", () => {
  const events = [
    { type: "content", turn_id: "turn_stream" },
    { type: "result", turn_id: "turn_result" },
  ];
  assert.equal(extractQuizTurnId(events), "turn_result");
});

test("extractQuizTurnId skips events without a turn id", () => {
  const events = [
    { type: "session" },
    { type: "content", turn_id: "" },
    { type: "content", turn_id: "turn_C" },
  ];
  assert.equal(extractQuizTurnId(events), "turn_C");
});

test("extractQuizTurnId returns null for legacy turn-less events", () => {
  assert.equal(extractQuizTurnId(undefined), null);
  assert.equal(extractQuizTurnId([]), null);
  assert.equal(extractQuizTurnId([{ type: "content" }]), null);
});
