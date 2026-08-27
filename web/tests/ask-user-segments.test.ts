import test from "node:test";
import assert from "node:assert/strict";
import {
  extractMessageSegments,
  leadingTraceEvents,
} from "../components/chat/home/AskUserOptions";
import type { StreamEvent } from "../lib/unified-ws";

function event(
  type: StreamEvent["type"],
  metadata: Record<string, unknown> = {},
  content = "",
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

const askUserCard = (toolCallId: string) =>
  event("tool_result", {
    tool_call_id: toolCallId,
    tool_metadata: {
      ask_user: {
        questions: [
          {
            id: "q1",
            prompt: "Which is the general form?",
            options: [{ label: "A" }, { label: "B" }],
          },
        ],
      },
    },
  });

const resolved = (toolCallId: string) =>
  event("progress", {
    ask_user_resolved: true,
    ask_user_tool_call_id: toolCallId,
    answers: [{ questionId: "q1", text: "B" }],
  });

test("reasoning produced after a card becomes its own segment below it", () => {
  const before = event(
    "thinking",
    { call_id: "round-1" },
    "planning a question",
  );
  const after = event(
    "thinking",
    { call_id: "round-2" },
    "grading their answer",
  );

  const segments = extractMessageSegments([
    before,
    askUserCard("call-1"),
    resolved("call-1"),
    after,
    event(
      "content",
      { call_id: "round-2", call_kind: "agent_loop_round" },
      "Correct!",
    ),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["ask_user", "trace", "text"],
  );
  const traceSegment = segments[1];
  assert.equal(traceSegment.kind === "trace" && traceSegment.events.length, 1);
  assert.equal(
    traceSegment.kind === "trace" && traceSegment.events[0].content,
    "grading their answer",
  );
});

test("the pre-card rounds stay with the top activity block", () => {
  const before = event("thinking", { call_id: "round-1" }, "planning");
  const after = event("thinking", { call_id: "round-2" }, "grading");
  const events = [before, askUserCard("call-1"), resolved("call-1"), after];

  const leading = leadingTraceEvents(events, extractMessageSegments(events));

  assert.deepEqual(leading, [
    before,
    askUserCard("call-1"),
    resolved("call-1"),
  ]);
});

test("a turn with no card keeps every event in the top block", () => {
  const events = [
    event("thinking", { call_id: "round-1" }, "thinking"),
    event(
      "content",
      { call_id: "round-1", call_kind: "agent_loop_round" },
      "answer",
    ),
  ];
  const segments = extractMessageSegments(events);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text"],
  );
  assert.deepEqual(leadingTraceEvents(events, segments), events);
});

test("each card gets the rounds that followed it", () => {
  const segments = extractMessageSegments([
    askUserCard("call-1"),
    resolved("call-1"),
    event("thinking", { call_id: "round-2" }, "first follow-up"),
    askUserCard("call-2"),
    resolved("call-2"),
    event("thinking", { call_id: "round-3" }, "second follow-up"),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["ask_user", "trace", "ask_user", "trace"],
  );
});
