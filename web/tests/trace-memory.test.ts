import assert from "node:assert/strict";
import test from "node:test";

import type { StreamEvent } from "../features/chat/model/protocol";
import {
  MAX_LEGACY_PAYLOAD_CHARS,
  TraceCache,
  compactTracePreview,
  settleMessageTrace,
} from "../features/chat/trace/memory";

function event(
  type: StreamEvent["type"],
  content = "",
  metadata: Record<string, unknown> = {},
): StreamEvent {
  return {
    type,
    source: "chat",
    stage: "",
    content,
    metadata,
    timestamp: 1,
  };
}

test("trace previews keep semantic state and bound legacy payloads", () => {
  const preview = compactTracePreview([
    event("content", "delta"),
    event("tool_result", "x".repeat(MAX_LEGACY_PAYLOAD_CHARS + 2)),
    event("result", "", { summary: "ok" }),
    event("done", "", { status: "completed" }),
  ]);

  assert.equal(preview.truncated, true);
  assert.deepEqual(
    preview.events.map((item) => item.type),
    ["tool_result", "result", "done"],
  );
  const bounded = preview.events[0].content ?? "";
  assert.equal(
    bounded.length,
    MAX_LEGACY_PAYLOAD_CHARS + "...[truncated]".length,
  );
});

test("expanded trace cache evicts the oldest message beyond five entries", () => {
  const cache = new TraceCache(5);
  for (let index = 0; index < 6; index += 1) {
    cache.retain(`session:${index}`, { events: [event("done")] });
  }

  const evicted = cache.release("session:0");
  assert.equal(evicted, undefined);
  assert.equal(cache.has("session:1"), true);
  assert.equal(cache.has("session:5"), true);
  assert.equal(cache.size, 5);
});

test("trace previews preserve early critical state before the event cap", () => {
  const preview = compactTracePreview(
    [
      event("content", "", { ask_user: true }),
      event("tool_result"),
      event("tool_result"),
      event("done"),
    ],
    2,
  );

  assert.deepEqual(
    preview.events.map((item) => item.type),
    ["content", "done"],
  );
});

test("a posed mastery question outranks trace rows the same way a card does", () => {
  // The card has its own metadata key now; the compactor had to learn it, or
  // a long course turn dropped the question and kept the chatter.
  const preview = compactTracePreview(
    [
      event("tool_result", "", {
        tool_metadata: { mastery_question: { question_id: "q-1" } },
      }),
      event("tool_result"),
      event("tool_result"),
      event("done"),
    ],
    2,
  );

  assert.equal(
    preview.events.some(
      (item) =>
        (
          (item.metadata as { tool_metadata?: { mastery_question?: unknown } })
            ?.tool_metadata ?? {}
        ).mastery_question !== undefined,
    ),
    true,
  );
});

test("settling a message keeps its card and stamps where the answer was cut", () => {
  const card = event("tool_result", "", {
    call_id: "tool-1",
    tool_metadata: {
      ask_user: { questions: [{ id: "q1", prompt: "Pick one" }] },
    },
  });
  const settled = settleMessageTrace(
    [
      {
        ...event("content", "preamble ", {
          call_id: "round-1",
          call_kind: "agent_loop_round",
        }),
        seq: 1,
      },
      {
        ...event("progress", "", {
          call_id: "round-1",
          trace_kind: "call_status",
          call_state: "complete",
          call_role: "narration",
        }),
        seq: 2,
      },
      {
        ...event("content", "Two ways.\n\n", {
          call_id: "round-2",
          call_kind: "agent_loop_round",
        }),
        seq: 3,
      },
      { ...card, seq: 4 },
      {
        ...event("progress", "", {
          ask_user_resolved: true,
          ask_user_tool_call_id: "tool-1",
        }),
        seq: 5,
      },
      {
        ...event("content", "Because B.", {
          call_id: "round-3",
          call_kind: "agent_loop_round",
        }),
        seq: 6,
      },
      { ...event("done", "", { status: "completed" }), seq: 7 },
    ],
    "turn-1",
  );

  assert.deepEqual(
    settled.events.map((item) => item.type),
    ["tool_result", "progress", "done"],
  );
  // The narration preamble never reached the answer, so it is not counted.
  assert.equal(
    settled.events[1].metadata?.assistant_content_offset,
    "Two ways.\n\n".length,
  );
  assert.deepEqual(settled.trace, {
    turn_id: "turn-1",
    total: 7,
    last_seq: 7,
    truncated: true,
    // Measured over the full stream, before the preview drops the events that
    // mark where the turn began — this fixture stamps every event at 1.
    started_at: 1,
    ended_at: 1,
  });
});
