import assert from "node:assert/strict";
import test from "node:test";

import type { StreamEvent } from "../features/chat/model/protocol";
import {
  MAX_LEGACY_PAYLOAD_CHARS,
  TraceCache,
  compactTracePreview,
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
