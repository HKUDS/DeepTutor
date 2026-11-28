import test from "node:test";
import assert from "node:assert/strict";
import {
  MIN_REGION_SIDE,
  boxToTuple,
  regionFromDrag,
} from "../lib/pdf-page-geometry";

// A page surface drawn at 100,50 and 400x600 CSS px.
const SURFACE = { left: 100, top: 50, width: 400, height: 600 };

test("a drag is normalised against the whole-page surface", () => {
  const box = regionFromDrag({ x: 140, y: 110 }, { x: 300, y: 350 }, SURFACE);
  assert.deepEqual(box, { x0: 0.1, y0: 0.1, x1: 0.5, y1: 0.5 });
});

test("a drag up and to the left gives the same ordered box", () => {
  assert.deepEqual(
    regionFromDrag({ x: 300, y: 350 }, { x: 140, y: 110 }, SURFACE),
    regionFromDrag({ x: 140, y: 110 }, { x: 300, y: 350 }, SURFACE),
  );
});

test("a drag past the page edge is clamped to the page", () => {
  const box = regionFromDrag({ x: 20, y: 0 }, { x: 900, y: 1000 }, SURFACE);
  assert.deepEqual(box, { x0: 0, y0: 0, x1: 1, y1: 1 });
});

test("a click or a sliver is not an area", () => {
  assert.equal(regionFromDrag({ x: 200, y: 200 }, { x: 200, y: 200 }, SURFACE), null);
  // Wide but only 2px (0.0033 of the page) tall.
  assert.equal(regionFromDrag({ x: 120, y: 200 }, { x: 480, y: 202 }, SURFACE), null);
  // Exactly at the floor counts.
  const side = MIN_REGION_SIDE * SURFACE.width;
  assert.notEqual(
    regionFromDrag({ x: 200, y: 200 }, { x: 200 + side, y: 200 + side * 1.5 }, SURFACE),
    null,
  );
});

test("a drag entirely beside the page collapses to nothing", () => {
  assert.equal(regionFromDrag({ x: 520, y: 100 }, { x: 700, y: 400 }, SURFACE), null);
});

test("an unmeasured surface marks nothing", () => {
  const empty = { left: 0, top: 0, width: 0, height: 0 };
  assert.equal(regionFromDrag({ x: 0, y: 0 }, { x: 10, y: 10 }, empty), null);
  assert.equal(
    regionFromDrag({ x: Number.NaN, y: 0 }, { x: 10, y: 10 }, SURFACE),
    null,
  );
});

test("the wire tuple keeps x0, y0, x1, y1 order at four places", () => {
  assert.deepEqual(boxToTuple({ x0: 0.123456, y0: 0.2, x1: 0.987654, y1: 1 }), [
    0.1235, 0.2, 0.9877, 1,
  ]);
});
