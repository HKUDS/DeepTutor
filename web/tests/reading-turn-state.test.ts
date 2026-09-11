import test from "node:test";
import assert from "node:assert/strict";
import {
  READING_WORKSPACE_MODE,
  getReadingTurnState,
  normalizeReadingMaterialId,
  normalizeReadingMaterialRevision,
  readingTurnFields,
  resetReadingTurnState,
  setReadingMaterial,
  setReadingViewport,
  setReadingWorkspace,
} from "../lib/reading-turn-state";

test.beforeEach(() => resetReadingTurnState());

test("normalizes persisted reading material ids and rejects unsafe values", () => {
  assert.equal(
    normalizeReadingMaterialId(" 0123456789ABCDEF "),
    "0123456789abcdef",
  );
  assert.equal(normalizeReadingMaterialId("../../etc/passwd"), null);
  assert.equal(normalizeReadingMaterialId("0123"), null);
  assert.equal(normalizeReadingMaterialId(null), null);
});

test("normalizes immutable material revisions", () => {
  assert.equal(normalizeReadingMaterialRevision(3), 3);
  assert.equal(normalizeReadingMaterialRevision("4"), 4);
  assert.equal(normalizeReadingMaterialRevision(0), null);
  assert.equal(normalizeReadingMaterialRevision(1.5), null);
  assert.equal(normalizeReadingMaterialRevision("nope"), null);
});

test("carries the document and viewport for every action inside reading", () => {
  setReadingMaterial("d138eacaad029843", 4);
  setReadingViewport({ locator: 3, selection: "attention" });

  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {
    reading_material_id: "d138eacaad029843",
    reading_material_revision: 4,
    reading_viewport: { locator: 3, selection: "attention" },
  });
});

// Regression: the open document lives in a provider mounted in the workspace
// layout, so it survives a mode switch AND a new session. Keying only on "is a
// document open" attached the reader to every later turn — a brand-new chat
// session would open with "I see you're reading …" and cite pages from a
// document the user had moved on from.
test("changing the per-turn action does not detach the reading workspace", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 3 });

  for (const capability of ["", "deep_solve", "deep_research", "visualize"]) {
    assert.deepEqual(
      readingTurnFields(READING_WORKSPACE_MODE),
      {
        reading_material_id: "d138eacaad029843",
        reading_viewport: { locator: 3 },
      },
      capability,
    );
  }
});

test("carries nothing when the workspace mode is absent", () => {
  setReadingMaterial("d138eacaad029843");
  assert.deepEqual(readingTurnFields(null), {});
  assert.deepEqual(readingTurnFields(undefined), {});
});

test("leaving the reading workspace stops carrying its document", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 7 });

  assert.deepEqual(readingTurnFields(null), {});
  // The reader cell remains intact so returning to the workspace resumes it.
  assert.equal(getReadingTurnState().materialId, "d138eacaad029843");
  assert.equal(
    readingTurnFields(READING_WORKSPACE_MODE).reading_viewport?.locator,
    7,
  );
});

test("carries nothing in reading mode with no document open", () => {
  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {});
});

test("closing the document clears its viewport too", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 9, selection: "x" });
  setReadingMaterial(null);

  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {});
  assert.deepEqual(getReadingTurnState(), {
    workspaceId: null,
    materialId: null,
    materialRevision: null,
    locator: 0,
    selection: "",
    timeSeconds: null,
  });
});

test("carries the private workspace and clears it independently", () => {
  setReadingWorkspace("workspace_123");
  setReadingMaterial("d138eacaad029843");

  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {
    reading_workspace_id: "workspace_123",
    reading_material_id: "d138eacaad029843",
  });

  setReadingWorkspace(null);
  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {});
  assert.deepEqual(getReadingTurnState(), {
    workspaceId: null,
    materialId: null,
    materialRevision: null,
    locator: 0,
    selection: "",
    timeSeconds: null,
  });
});

test("a viewport with no locator or selection is omitted, not sent empty", () => {
  setReadingMaterial("d138eacaad029843");
  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE), {
    reading_material_id: "d138eacaad029843",
  });
});

test("nonsense viewport values are ignored", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: -3 });
  assert.equal(
    readingTurnFields(READING_WORKSPACE_MODE).reading_viewport,
    undefined,
  );
  setReadingViewport({ locator: 2.7 });
  assert.equal(
    readingTurnFields(READING_WORKSPACE_MODE).reading_viewport?.locator,
    2,
  );
});

test("carries precise media time, including the beginning", () => {
  setReadingMaterial("d138eacaad029843");
  setReadingViewport({ locator: 2, timeSeconds: 62.5 });
  assert.deepEqual(readingTurnFields(READING_WORKSPACE_MODE).reading_viewport, {
    locator: 2,
    time_seconds: 62.5,
  });

  setReadingViewport({ timeSeconds: 0 });
  assert.equal(
    readingTurnFields(READING_WORKSPACE_MODE).reading_viewport?.time_seconds,
    0,
  );
});
