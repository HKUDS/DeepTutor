import test from "node:test";
import assert from "node:assert/strict";
import {
  cleanQuote,
  locatorOfSelection,
  mergeRectsByLine,
  normaliseRects,
  unionRect,
} from "../lib/reading-selection";

const box = (left: number, top: number, width: number, height: number) => ({
  left,
  top,
  width,
  height,
});

const PAGE = box(100, 200, 800, 1000);

test("merges rects that share a text line into one", () => {
  const merged = mergeRectsByLine([
    box(10, 10, 50, 14),
    box(60, 10, 40, 14),
    box(10, 30, 90, 14),
  ]);
  assert.equal(merged.length, 2);
  assert.deepEqual(merged[0], box(10, 10, 90, 14));
});

test("treats vertically overlapping rects of different heights as one line", () => {
  // A superscript sits higher and is shorter, but belongs to the same line.
  const merged = mergeRectsByLine([box(10, 10, 50, 14), box(60, 8, 8, 8)]);
  assert.equal(merged.length, 1);
});

test("drops sliver rects the browser emits at range edges", () => {
  const merged = mergeRectsByLine([box(10, 10, 50, 14), box(61, 10, 1, 14)]);
  assert.equal(merged.length, 1);
  assert.deepEqual(merged[0], box(10, 10, 50, 14));
});

test("no usable rects yields nothing rather than a degenerate box", () => {
  assert.deepEqual(mergeRectsByLine([]), []);
  assert.deepEqual(mergeRectsByLine([box(0, 0, 0, 0)]), []);
  assert.deepEqual(mergeRectsByLine([box(5, 5, 1, 1)]), []);
});

test("normalises to 0..1 of the container box", () => {
  const rects = normaliseRects([box(100, 200, 400, 100)], PAGE);
  assert.deepEqual(rects, [[0, 0, 0.5, 0.1]]);
});

test("normalisation is scroll-independent because both rects are viewport-space", () => {
  const scrolled = normaliseRects(
    [box(100 - 300, 200 - 300, 400, 100)],
    box(100 - 300, 200 - 300, 800, 1000),
  );
  assert.deepEqual(scrolled, [[0, 0, 0.5, 0.1]]);
});

test("clips a selection dragged off the page instead of discarding it", () => {
  const rects = normaliseRects([box(0, 100, 2000, 200)], PAGE);
  assert.equal(rects.length, 1);
  const [x0, y0, x1, y1] = rects[0];
  assert.ok(x0 >= 0 && y0 >= 0 && x1 <= 1 && y1 <= 1);
  assert.ok(x1 - x0 > 0);
});

test("a zero-sized container yields no rects rather than dividing by zero", () => {
  assert.deepEqual(normaliseRects([box(0, 0, 10, 10)], box(0, 0, 0, 0)), []);
});

test("drops rects that normalise to nothing", () => {
  // Entirely above the page: clamps to a zero-height sliver, so it is dropped.
  assert.deepEqual(normaliseRects([box(100, 0, 400, 4)], PAGE), []);
});

test("unionRect wraps every rect", () => {
  assert.deepEqual(
    unionRect([
      [0.1, 0.1, 0.4, 0.2],
      [0.05, 0.3, 0.6, 0.35],
    ]),
    [0.05, 0.1, 0.6, 0.35],
  );
  assert.equal(unionRect([]), null);
});

test("cleanQuote collapses the hard wraps a pdf text layer introduces", () => {
  assert.equal(
    cleanQuote("Transformers use scaled\n dot-product\tattention  today."),
    "Transformers use scaled dot-product attention today.",
  );
});

test("cleanQuote bounds an enormous selection", () => {
  assert.equal(cleanQuote("x".repeat(5000)).length, 2000);
  assert.equal(cleanQuote("x".repeat(50), 10).length, 10);
});

test("cleanQuote tolerates empty input", () => {
  assert.equal(cleanQuote(""), "");
  assert.equal(cleanQuote("   \n  "), "");
});

test("a cross-page selection is attributed to where it started", () => {
  assert.equal(locatorOfSelection([3, 4]), 3);
  assert.equal(locatorOfSelection([null, 4]), 4);
  assert.equal(locatorOfSelection([null, null]), null);
  assert.equal(locatorOfSelection([0, 2]), 2);
});
