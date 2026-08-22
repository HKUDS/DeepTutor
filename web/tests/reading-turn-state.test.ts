import test from "node:test";
import assert from "node:assert/strict";
import {
  READING_CAPABILITY,
  getReadingTurnState,
  readingTurnFields,
  resetReadingTurnState,
  setReadingMaterial,
  setReadingViewport,
} from "../lib/reading-turn-state";

test.beforeEach(() => resetReadingTurnState());

test("carries the document and viewport on a reading turn", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 3, selection: "attention" });

  assert.deepEqual(readingTurnFields(READING_CAPABILITY), {
    reading_material_id: "d138eacaad029843",
    reading_viewport: { locator: 3, selection: "attention" },
  });
});

// Regression: the open document lives in a provider mounted in the workspace
// layout, so it survives a mode switch AND a new session. Keying only on "is a
// document open" attached the reader to every later turn — a brand-new chat
// session would open with "I see you're reading …" and cite pages from a
// document the user had moved on from.
test("carries nothing once the user switches to another mode", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 3 });

  for (const capability of [
    "",
    "deep_solve",
    "deep_research",
    "mastery_path",
    "visualize",
  ]) {
    assert.deepEqual(readingTurnFields(capability), {}, capability);
  }
});

test("carries nothing when the capability is absent", () => {
  setReadingMaterial("d138eacaad029843");
  assert.deepEqual(readingTurnFields(null), {});
  assert.deepEqual(readingTurnFields(undefined), {});
});

test("the document itself is kept, so returning to the mode resumes it", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 7 });

  // Away…
  assert.deepEqual(readingTurnFields("deep_solve"), {});
  // …and back, with the reader still where it was.
  assert.equal(getReadingTurnState().materialId, "d138eacaad029843");
  assert.equal(
    readingTurnFields(READING_CAPABILITY).reading_viewport?.locator,
    7,
  );
});

test("carries nothing in reading mode with no document open", () => {
  assert.deepEqual(readingTurnFields(READING_CAPABILITY), {});
});

test("closing the document clears its viewport too", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 9, selection: "x" });
  setReadingMaterial(null);

  assert.deepEqual(readingTurnFields(READING_CAPABILITY), {});
  assert.deepEqual(getReadingTurnState(), {
    materialId: null,
    locator: 0,
    selection: "",
  });
});

test("a viewport with no locator or selection is omitted, not sent empty", () => {
  setReadingMaterial("d138eacaad029843");
  assert.deepEqual(readingTurnFields(READING_CAPABILITY), {
    reading_material_id: "d138eacaad029843",
  });
});

test("nonsense viewport values are ignored", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: -3 });
  assert.equal(
    readingTurnFields(READING_CAPABILITY).reading_viewport,
    undefined,
  );
  setReadingViewport({ locator: 2.7 });
  assert.equal(
    readingTurnFields(READING_CAPABILITY).reading_viewport?.locator,
    2,
  );
});
