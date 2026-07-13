import test from "node:test";
import assert from "node:assert/strict";
import {
  hasPendingAskUser,
  hasPendingAskUserInMessages,
} from "../lib/ask-user-state";
import type { StreamEvent } from "../lib/unified-ws";

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
