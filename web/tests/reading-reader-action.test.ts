import test from "node:test";
import assert from "node:assert/strict";
import { readerActionFrom } from "../lib/reading-reader-action";

// The shape the dispatcher actually emits: the tool's own metadata is NESTED
// under `tool_metadata`, next to the dispatcher's trace keys. Reading the top
// level instead type-checks fine and silently never matches — which is exactly
// how the reader ended up ignoring every reader_goto the model made.
const realEvent = (toolMetadata: Record<string, unknown>) => ({
  type: "tool_result",
  metadata: {
    tool: "reader_goto",
    trace_kind: "tool_result",
    trace_id: "chat-1",
    tool_metadata: toolMetadata,
  },
});

test("reads a goto out of the dispatcher's nested metadata", () => {
  const action = readerActionFrom(
    realEvent({
      material_id: "d138eacaad029843",
      reader_action: "goto",
      locator: 5,
      quote: "Removing recurrence entirely",
      corrected_from: null,
    }),
  );
  assert.ok(action);
  assert.equal(action.reader_action, "goto");
  assert.equal(action.locator, 5);
  assert.equal(action.quote, "Removing recurrence entirely");
  assert.equal(action.material_id, "d138eacaad029843");
});

test("reads an annotate, carrying the stored row", () => {
  const action = readerActionFrom(
    realEvent({
      reader_action: "annotate",
      locator: 2,
      annotation: { annotation_id: "abc123", locator: 2, quote: "x" },
    }),
  );
  assert.ok(action);
  assert.equal(action.reader_action, "annotate");
  assert.equal(
    (action.annotation as { annotation_id: string }).annotation_id,
    "abc123",
  );
});

test("still accepts a flat payload, for events emitted directly", () => {
  const action = readerActionFrom({
    type: "tool_result",
    metadata: { reader_action: "goto", locator: 3 },
  });
  assert.ok(action);
  assert.equal(action.locator, 3);
});

test("ignores tool results that carry no reader action", () => {
  assert.equal(
    readerActionFrom(realEvent({ material_id: "abc", locators: [1, 2] })),
    null,
  );
  assert.equal(
    readerActionFrom({ type: "tool_result", metadata: { tool: "web_search" } }),
    null,
  );
});

test("ignores every other event type", () => {
  for (const type of ["content", "tool_call", "done", "sources", "error"]) {
    assert.equal(
      readerActionFrom({
        type,
        metadata: { tool_metadata: { reader_action: "goto", locator: 1 } },
      }),
      null,
      type,
    );
  }
});

test("drops nonsense locators rather than jumping somewhere arbitrary", () => {
  assert.equal(
    readerActionFrom(realEvent({ reader_action: "goto", locator: 0 }))?.locator,
    undefined,
  );
  assert.equal(
    readerActionFrom(realEvent({ reader_action: "goto", locator: -2 }))
      ?.locator,
    undefined,
  );
  assert.equal(
    readerActionFrom(realEvent({ reader_action: "goto", locator: "abc" }))
      ?.locator,
    undefined,
  );
});

test("tolerates malformed metadata", () => {
  assert.equal(readerActionFrom({ type: "tool_result" }), null);
  assert.equal(readerActionFrom({ type: "tool_result", metadata: null }), null);
  assert.equal(
    readerActionFrom({ type: "tool_result", metadata: "nope" }),
    null,
  );
  assert.equal(
    readerActionFrom({
      type: "tool_result",
      metadata: { tool_metadata: "nope" },
    }),
    null,
  );
});

// ── Turn-end fallback ───────────────────────────────────────────────────────
// The model is asked to call reader_goto per passage, and mostly does — but a
// turn that cites [p.5] while the reader sits on page 1 looks broken regardless
// of whose fault it is. The pane needs to know whether the turn ever moved it.

import {
  READER_TURN_END_EVENT,
  forwardReaderAction,
  resetReaderActionTracking,
} from "../lib/reading-reader-action";

/** Minimal window stub: these functions only dispatch DOM events. */
function withWindow<T>(
  run: (seen: Array<{ type: string; detail: unknown }>) => T,
): T {
  const seen: Array<{ type: string; detail: unknown }> = [];
  const previous = (globalThis as { window?: unknown }).window;
  (globalThis as { window?: unknown }).window = {
    dispatchEvent: (e: { type: string; detail: unknown }) => {
      seen.push({ type: e.type, detail: e.detail });
      return true;
    },
  };
  class FakeCustomEvent {
    type: string;
    detail: unknown;
    constructor(type: string, init?: { detail?: unknown }) {
      this.type = type;
      this.detail = init?.detail;
    }
  }
  const prevCE = (globalThis as { CustomEvent?: unknown }).CustomEvent;
  (globalThis as { CustomEvent?: unknown }).CustomEvent = FakeCustomEvent;
  try {
    return run(seen);
  } finally {
    (globalThis as { window?: unknown }).window = previous;
    (globalThis as { CustomEvent?: unknown }).CustomEvent = prevCE;
  }
}

const gotoEvent = (turnId: string) => ({
  type: "tool_result",
  turn_id: turnId,
  metadata: { tool_metadata: { reader_action: "goto", locator: 5 } },
});

test("a turn that moved the reader reports moved=true", () => {
  resetReaderActionTracking();
  withWindow((seen) => {
    forwardReaderAction(gotoEvent("turn-1"));
    forwardReaderAction({ type: "done", turn_id: "turn-1" });
    const end = seen.find((e) => e.type === READER_TURN_END_EVENT);
    assert.ok(end);
    assert.deepEqual(end.detail, { moved: true });
  });
});

test("a turn that never moved it reports moved=false, so the pane can follow", () => {
  resetReaderActionTracking();
  withWindow((seen) => {
    forwardReaderAction({ type: "content", turn_id: "turn-2" });
    forwardReaderAction({ type: "done", turn_id: "turn-2" });
    const end = seen.find((e) => e.type === READER_TURN_END_EVENT);
    assert.deepEqual(end?.detail, { moved: false });
  });
});

test("turns are tracked separately", () => {
  resetReaderActionTracking();
  withWindow((seen) => {
    forwardReaderAction(gotoEvent("turn-a"));
    forwardReaderAction({ type: "done", turn_id: "turn-b" });
    assert.deepEqual(
      seen.find((e) => e.type === READER_TURN_END_EVENT)?.detail,
      { moved: false },
    );
    forwardReaderAction({ type: "done", turn_id: "turn-a" });
    assert.deepEqual(
      seen.filter((e) => e.type === READER_TURN_END_EVENT)[1]?.detail,
      { moved: true },
    );
  });
});

test("a turn's record is cleared once it ends", () => {
  resetReaderActionTracking();
  withWindow((seen) => {
    forwardReaderAction(gotoEvent("turn-3"));
    forwardReaderAction({ type: "done", turn_id: "turn-3" });
    forwardReaderAction({ type: "done", turn_id: "turn-3" });
    const ends = seen.filter((e) => e.type === READER_TURN_END_EVENT);
    assert.deepEqual(ends[0].detail, { moved: true });
    assert.deepEqual(ends[1].detail, { moved: false });
  });
});

test("annotate alone does not count as having moved the reader", () => {
  resetReaderActionTracking();
  withWindow((seen) => {
    forwardReaderAction({
      type: "tool_result",
      turn_id: "turn-4",
      metadata: {
        tool_metadata: {
          reader_action: "annotate",
          locator: 2,
          annotation: { annotation_id: "a" },
        },
      },
    });
    forwardReaderAction({ type: "done", turn_id: "turn-4" });
    assert.deepEqual(
      seen.find((e) => e.type === READER_TURN_END_EVENT)?.detail,
      { moved: false },
    );
  });
});
