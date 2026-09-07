import assert from "node:assert/strict";
import test from "node:test";

import { parseReadingPosition } from "@/lib/reading-api";

test("reading positions accept the complete API contract", () => {
  const position = {
    locator: 3,
    source_anchor: "chapter-3",
    percentage: 0.5,
    updated_at: 42,
  };

  assert.deepEqual(parseReadingPosition(position), position);
});

test("reading positions reject partial and non-finite responses", () => {
  assert.throws(
    () => parseReadingPosition({}),
    /Invalid reading position response/,
  );
  assert.throws(
    () =>
      parseReadingPosition({
        locator: Number.NaN,
        source_anchor: "",
        percentage: 0,
        updated_at: 0,
      }),
    /Invalid reading position response/,
  );
});
