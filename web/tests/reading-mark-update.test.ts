import test from "node:test";
import assert from "node:assert/strict";
import { buildMarkUpdate } from "../lib/reading-mark-update";
import type { AnnotationItem } from "../lib/reading-api";

function mark(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "a1",
    locator: 3,
    kind: "highlight",
    color: "yellow",
    quote: "the latency budget",
    note: "original",
    rects: [[0.1, 0.2, 0.5, 0.24]],
    source_anchor: "",
    selectors: [],
    author: "user",
    created_at: 10,
    updated_at: 10,
    ...overrides,
  } as AnnotationItem;
}

/**
 * The rule every surface that edits a mark shares.
 *
 * It was extracted so the reader pane and the workspace navigator cannot
 * disagree, and it had no direct test — its callers are mocked in the
 * component tests, so nothing exercised it.
 */
test("changing the note keeps everything that anchors the mark", () => {
  const update = buildMarkUpdate(mark(), { note: "revised" });
  assert.ok(update);
  assert.equal(update.draft.note, "revised");
  // Re-sending different anchoring fields would move the highlight.
  assert.equal(update.draft.quote, "the latency budget");
  assert.deepEqual(update.draft.rects, [[0.1, 0.2, 0.5, 0.24]]);
  assert.equal(update.draft.locator, 3);
  assert.equal(update.draft.annotation_id, "a1");
  // created_at is what the mark is, and must survive the edit.
  assert.equal(update.optimistic.created_at, 10);
});

test("trims the note it sends", () => {
  const update = buildMarkUpdate(mark(), { note: "  spaced  " });
  assert.ok(update);
  assert.equal(update.draft.note, "spaced");
});

test("bumps updated_at on a real change", () => {
  const update = buildMarkUpdate(mark(), { color: "green" });
  assert.ok(update);
  assert.ok(update.optimistic.updated_at > 10);
});

test("reports no update when nothing actually changed", () => {
  // The caller skips the round trip rather than bumping updated_at for a no-op.
  assert.equal(buildMarkUpdate(mark(), { note: "original" }), null);
  assert.equal(buildMarkUpdate(mark(), { color: "yellow" }), null);
  assert.equal(buildMarkUpdate(mark(), { kind: "highlight" }), null);
  assert.equal(buildMarkUpdate(mark(), {}), null);
});

test("refuses to wipe a note by emptying it", () => {
  // An emptied note is a delete in disguise, and deleting is its own action.
  assert.equal(buildMarkUpdate(mark(), { note: "" }), null);
  assert.equal(buildMarkUpdate(mark(), { note: "   " }), null);
});

test("changes the colour without touching the note", () => {
  const update = buildMarkUpdate(mark(), { color: "green" });
  assert.ok(update);
  assert.equal(update.draft.color, "green");
  assert.equal(update.draft.note, "original");
});

test("changes the kind", () => {
  const update = buildMarkUpdate(mark(), { kind: "underline" });
  assert.ok(update);
  assert.equal(update.draft.kind, "underline");
});

test("applies several changes at once", () => {
  const update = buildMarkUpdate(mark(), { note: "new", color: "blue", kind: "underline" });
  assert.ok(update);
  assert.equal(update.draft.note, "new");
  assert.equal(update.draft.color, "blue");
  assert.equal(update.draft.kind, "underline");
});

test("defaults selectors to an empty list when the mark has none", () => {
  const update = buildMarkUpdate(mark({ selectors: undefined }), { color: "pink" });
  assert.ok(update);
  assert.deepEqual(update.draft.selectors, []);
});
