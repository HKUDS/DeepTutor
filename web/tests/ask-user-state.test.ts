import test from "node:test";
import assert from "node:assert/strict";
import {
  hasPendingAskUser,
  hasPendingAskUserInMessages,
  hasPendingUserCard,
} from "../lib/ask-user-state";
import type { StreamEvent } from "../features/chat/model/protocol";

function event(
  type: StreamEvent["type"],
  metadata: Record<string, unknown>,
  turnId = "turn-1",
): StreamEvent {
  return {
    type,
    source: "test",
    stage: "rephrasing",
    content: "",
    metadata,
    session_id: "session-1",
    turn_id: turnId,
    seq: 1,
    timestamp: 0,
  };
}

test("hasPendingAskUser detects unresolved ask_user tool results", () => {
  const events = [
    event("tool_result", {
      tool_call_id: "call-1",
      tool_metadata: {
        ask_user: {
          questions: [{ id: "scope", prompt: "What scope?" }],
        },
      },
    }),
  ];

  assert.equal(hasPendingAskUser(events, "turn-1"), true);
});

test("hasPendingAskUser clears the matching card after ask_user_resolved", () => {
  const events = [
    event("tool_result", {
      tool_call_id: "call-1",
      tool_metadata: {
        ask_user: { questions: [{ id: "scope", prompt: "Scope?" }] },
      },
    }),
    event("progress", {
      ask_user_resolved: true,
      ask_user_tool_call_id: "call-1",
    }),
  ];

  assert.equal(hasPendingAskUser(events, "turn-1"), false);
});

test("hasPendingAskUserInMessages ignores ask_user cards from other turns", () => {
  const messages = [
    {
      events: [
        event(
          "tool_result",
          {
            tool_call_id: "call-old",
            tool_metadata: {
              ask_user: { questions: [{ id: "q", prompt: "Old?" }] },
            },
          },
          "turn-old",
        ),
      ],
    },
  ];

  assert.equal(hasPendingAskUserInMessages(messages, "turn-1"), false);
});

test("a posed mastery question is a waiting card but never a live pause", () => {
  // ``mastery_quiz`` poses the question and stops the turn: the answer opens
  // the next one, so no ``ask_user_resolved`` ever arrives. Counted as a live
  // pause, it made every later message get routed into a
  // ``submit_user_reply`` the backend refused — which is why the card no
  // longer travels on this channel at all.
  const events = [
    event("tool_result", {
      tool_call_id: "call-quiz",
      tool_metadata: {
        mastery_question: { question_id: "q-1", prompt: "Which reducer?" },
      },
    }),
  ];

  assert.equal(hasPendingAskUser(events, "turn-1"), false);
  assert.equal(hasPendingUserCard(events, "turn-1"), true);
});

test("hasPendingAskUser ignores a legacy mastery card on the ask_user channel", () => {
  // ``mastery_quiz`` poses the question and stops the turn: the answer opens
  // the next one, so no ``ask_user_resolved`` ever arrives. Counted as a live
  // pause, it made every later message — including a question about the
  // material — get routed into a ``submit_user_reply`` the backend refused.
  const events = [
    event("tool_result", {
      tool_call_id: "call-quiz",
      tool_metadata: {
        ask_user: {
          kind: "mastery_question",
          mastery_question: { question_id: "q-1", prompt: "Which reducer?" },
          questions: [{ id: "q-1", prompt: "Which reducer?" }],
        },
      },
    }),
  ];

  assert.equal(hasPendingAskUser(events, "turn-1"), false);
  assert.equal(hasPendingUserCard(events, "turn-1"), true);
});

test("a mastery card does not mask a real pause in the same turn", () => {
  const events = [
    event("tool_result", {
      tool_call_id: "call-quiz",
      tool_metadata: {
        ask_user: {
          kind: "mastery_question",
          mastery_question: { question_id: "q-1", prompt: "Which reducer?" },
        },
      },
    }),
    event("tool_result", {
      tool_call_id: "call-ask",
      tool_metadata: {
        ask_user: { questions: [{ id: "s", prompt: "Scope?" }] },
      },
    }),
  ];

  assert.equal(hasPendingAskUser(events, "turn-1"), true);
});
