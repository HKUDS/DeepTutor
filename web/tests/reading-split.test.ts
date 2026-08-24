import test from "node:test";
import assert from "node:assert/strict";
import {
  CHAT_MIN_PX,
  READER_MAX_PX,
  READER_MIN_PX,
  clampReaderWidth,
  parseStoredWidth,
} from "../lib/reading-split";

test("keeps a reasonable width untouched", () => {
  assert.equal(clampReaderWidth(900, 1380), 900);
  assert.equal(clampReaderWidth(600, 1380), 600);
});

test("never lets the reader get too narrow to read", () => {
  assert.equal(clampReaderWidth(50, 1380), READER_MIN_PX);
  assert.equal(clampReaderWidth(0, 1380), READER_MIN_PX);
  assert.equal(clampReaderWidth(-400, 1380), READER_MIN_PX);
});

test("always leaves the conversation a usable column", () => {
  const available = 1380;
  const widest = clampReaderWidth(99999, available);
  assert.equal(available - widest, CHAT_MIN_PX);
});

test("respects the absolute ceiling on a very wide display", () => {
  // 4000 - 380 = 3620, but no reader needs to be wider than READER_MAX_PX.
  assert.equal(clampReaderWidth(99999, 4000), READER_MAX_PX);
});

test("on a narrow container the reader floor wins over the chat floor", () => {
  // 600 - 380 = 220, below the reader minimum. Overflowing slightly beats a
  // 220px reader; below `lg` the split does not exist at all.
  assert.equal(clampReaderWidth(500, 600), READER_MIN_PX);
});

test("an unknown container falls back to the absolute bounds", () => {
  // Server render, or a measurement taken before layout. The CSS carries its
  // own percentage ceiling for exactly this case.
  assert.equal(clampReaderWidth(99999, 0), READER_MAX_PX);
  assert.equal(clampReaderWidth(900, 0), 900);
  assert.equal(clampReaderWidth(10, -1), READER_MIN_PX);
});

test("nonsense input degrades to the minimum rather than NaN", () => {
  assert.equal(clampReaderWidth(Number.NaN, 1380), READER_MIN_PX);
  assert.equal(clampReaderWidth(Number.POSITIVE_INFINITY, 1380), READER_MIN_PX);
});

test("always returns a whole pixel", () => {
  assert.equal(clampReaderWidth(700.6, 1380), 701);
  assert.ok(Number.isInteger(clampReaderWidth(612.4, 1380)));
});

test("parseStoredWidth accepts a stored number and rejects junk", () => {
  assert.equal(parseStoredWidth("820"), 820);
  assert.equal(parseStoredWidth("820.5"), 820.5);
  assert.equal(parseStoredWidth(null), null);
  assert.equal(parseStoredWidth(""), null);
  assert.equal(parseStoredWidth("wide"), null);
  assert.equal(parseStoredWidth("0"), null);
  assert.equal(parseStoredWidth("-500"), null);
  assert.equal(parseStoredWidth("Infinity"), null);
});
