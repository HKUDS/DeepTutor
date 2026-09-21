import assert from "node:assert/strict";
import test from "node:test";
import type { StreamEvent } from "../features/chat/model/protocol";
import {
  detectStreamingMode,
  groupTraceEvents,
  hasRenderableCallTrace,
  isRetractedRound,
  isTracePending,
  selectTraceDisplayItems,
} from "../features/chat/trace/selectors";

function event(
  type: StreamEvent["type"],
  callId: string,
  metadata: Record<string, unknown> = {},
  content = "",
): StreamEvent {
  return {
    type,
    source: "chat",
    stage: "exploring",
    content,
    metadata: { call_id: callId, ...metadata },
    timestamp: 1,
  };
}

test("trace groups preserve first-seen call order and event order", () => {
  const groups = groupTraceEvents([
    event("thinking", "a", {}, "one"),
    event("tool_call", "b", { tool_name: "rag" }),
    event("progress", "a", {}, "two"),
  ]);
  assert.deepEqual(
    groups.map((group) => group.callId),
    ["a", "b"],
  );
  assert.deepEqual(
    groups[0].events.map((item) => item.content),
    ["one", "two"],
  );
});

test("pending state ends only when its own call reports a terminal marker", () => {
  const running = [event("progress", "a", { call_state: "running" })];
  assert.equal(isTracePending(running), true);
  assert.equal(
    isTracePending([
      ...running,
      event("progress", "a", { call_state: "complete" }),
    ]),
    false,
  );
});

test("final answer and absorbed groups stay out of progressive trace disclosure", () => {
  const events = [
    event("content", "final", { call_kind: "llm_final_response" }, "Answer"),
    event("thinking", "absorbed", { absorbed_into_final: true }, "Draft"),
  ];
  assert.deepEqual(selectTraceDisplayItems(groupTraceEvents(events)), []);
  assert.equal(hasRenderableCallTrace(events), false);
});

test("only a retracted round's text becomes trace material", () => {
  // Chat-loop text lives in the answer bubble, so showing it in the trace as
  // well would print the same sentence twice. The exception is a round whose
  // text was taken back out — the trace is then the only place left for it.
  const commentary = [
    event(
      "content",
      "round-1",
      { call_kind: "agent_loop_round" },
      "I'll search.",
    ),
    event("progress", "round-1", {
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
      answer_visible: true,
    }),
  ];
  const retracted = [
    event(
      "content",
      "round-2",
      { call_kind: "agent_loop_round" },
      "A question I never posed",
    ),
    event("progress", "round-2", {
      trace_kind: "call_status",
      call_state: "complete",
      call_role: "narration",
      answer_visible: false,
    }),
  ];
  assert.equal(isRetractedRound(commentary), false);
  assert.equal(hasRenderableCallTrace(commentary), false);
  assert.equal(isRetractedRound(retracted), true);
  assert.equal(hasRenderableCallTrace(retracted), true);
});

test("adjacent react rounds and their trailing trace collapse into one display step", () => {
  const events = [
    event(
      "thinking",
      "round-1",
      { trace_group: "react_round", step_id: "step-1" },
      "Plan",
    ),
    event(
      "tool_call",
      "round-2",
      { trace_group: "react_round", step_id: "step-1" },
      "Search",
    ),
    event("thinking", "standalone", {}, "Reflect"),
  ];

  const items = selectTraceDisplayItems(groupTraceEvents(events));

  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "step");
  if (items[0].kind === "step") {
    assert.equal(items[0].stepId, "step-1");
    assert.deepEqual(
      items[0].traces.map((trace) => trace.callId),
      ["round-1", "round-2", "standalone"],
    );
  }
});

test("streaming mode follows the latest meaningful event", () => {
  assert.equal(
    detectStreamingMode([event("tool_call", "a")], false, true),
    "exploring",
  );
  assert.equal(
    detectStreamingMode(
      [event("thinking", "a", { call_kind: "tool_result_reflection" })],
      false,
      true,
    ),
    "reflecting",
  );
  assert.equal(detectStreamingMode([], true, false), "responded");
});
