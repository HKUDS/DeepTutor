import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_READING_REFERENCE_UNITS,
  normalizeReadingReferences,
  selectedReadingsToPayload,
} from "@/lib/reading-references";

test("selected reading units become a compact id-only payload", () => {
  assert.deepEqual(
    selectedReadingsToPayload([
      {
        materialId: "abcdef0123456789",
        revision: 3,
        materialTitle: "Attention",
        unit: "chapter",
        units: [
          { locator: 2, title: "Mechanism" },
          { locator: 2, title: "Duplicate" },
          { locator: 3, title: "Training" },
        ],
      },
    ]),
    [{ material_id: "abcdef0123456789", revision: 3, locators: [2, 3] }],
  );
});

test("malformed ids and locators are dropped at the client boundary", () => {
  assert.deepEqual(
    normalizeReadingReferences([
      { material_id: "../../etc", revision: 1, locators: [1] },
      {
        material_id: "ABCDEF0123456789",
        revision: 2,
        locators: [0, -1, 1.5, "2", 2],
      },
    ]),
    [{ material_id: "abcdef0123456789", revision: 2, locators: [2] }],
  );
});

test("reference payloads are bounded before they reach the websocket", () => {
  const refs = normalizeReadingReferences([
    {
      material_id: "abcdef0123456789",
      revision: 1,
      locators: Array.from({ length: 100 }, (_, index) => index + 1),
    },
  ]);

  assert.equal(refs[0].locators.length, MAX_READING_REFERENCE_UNITS);
});

test("empty rows do not consume the material limit", () => {
  const emptyRows = Array.from({ length: 20 }, (_, index) => ({
    material_id: index.toString(16).padStart(16, "0"),
    revision: 1,
    locators: [],
  }));

  assert.deepEqual(
    normalizeReadingReferences([
      ...emptyRows,
      { material_id: "abcdef0123456789", revision: 1, locators: [1] },
    ]),
    [{ material_id: "abcdef0123456789", revision: 1, locators: [1] }],
  );
});

test("references without a stable content revision fail closed", () => {
  assert.deepEqual(
    normalizeReadingReferences([
      { material_id: "abcdef0123456789", locators: [1] },
    ]),
    [],
  );
});
