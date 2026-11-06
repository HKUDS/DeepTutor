import test from "node:test";
import assert from "node:assert/strict";
import {
  cropLayout,
  inkBoxFromPixels,
} from "../lib/pdf-page-geometry";

function pixels(
  width: number,
  height: number,
  paint: (x: number, y: number) => boolean,
): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4;
      const ink = paint(x, y);
      data[index] = ink ? 0 : 255;
      data[index + 1] = ink ? 0 : 255;
      data[index + 2] = ink ? 0 : 255;
      data[index + 3] = 255;
    }
  }
  return data;
}

test("ink box follows the text block, not a page number in the gutter", () => {
  const width = 200;
  const height = 100;
  const data = pixels(width, height, (x, y) => {
    // Body text: a dense block between x=40 and x=160.
    if (x >= 40 && x < 160 && y >= 20 && y < 80) return true;
    // A page number in the left margin: three short glyph strokes.
    if (x >= 18 && x < 28 && y >= 90 && y < 92) return true;
    return false;
  });
  const box = inkBoxFromPixels(data, width, height);
  assert.ok(box);
  // The ink sits at 0.2–0.8; the box adds the padding either side of it.
  assert.ok(Math.abs(box.x0 - 0.18) < 0.005, `x0 was ${box.x0}`);
  assert.ok(Math.abs(box.x1 - 0.82) < 0.005, `x1 was ${box.x1}`);
  // Only the horizontal axis is cropped.
  assert.equal(box.y0, 0);
  assert.equal(box.y1, 1);
});

test("a cropped page keeps paper between the text and the cut", () => {
  // A table of contents: the title block starts at the left margin and the
  // page numbers stop just short of the right one, so the ink nearly spans the
  // page. Cropping exactly to it would leave the numbers on the cut.
  const data = pixels(200, 100, (x, y) => x >= 12 && x < 188 && y >= 10 && y < 90);
  const box = inkBoxFromPixels(data, 200, 100);
  assert.ok(box);
  assert.ok(12 / 200 - box.x0 > 0.015, `left padding was ${12 / 200 - box.x0}`);
  assert.ok(box.x1 - 188 / 200 > 0.015, `right padding was ${box.x1 - 188 / 200}`);
});

test("a page whose text reaches its margins is not trimmed", () => {
  // A contents page or a full-width table: cropping would gain a few percent
  // and put the last glyph on the cut, so fit-the-page is the honest answer.
  const data = pixels(200, 100, (x, y) => x >= 4 && x < 196 && y >= 10 && y < 90);
  assert.equal(inkBoxFromPixels(data, 200, 100), null);
});

test("a blank page has nothing to crop", () => {
  assert.equal(inkBoxFromPixels(pixels(80, 100, () => false), 80, 100), null);
});

test("a page with no usable margin reports no crop", () => {
  // Ink confined to a narrow strip would zoom past readability.
  const data = pixels(200, 100, (x, y) => x >= 90 && x < 110 && y > 10);
  assert.equal(inkBoxFromPixels(data, 200, 100), null);
});

test("crop layout widens the page so the strip fills the pane", () => {
  const layout = cropLayout(600, 1.4, { x0: 0.25, y0: 0, x1: 0.75, y1: 1 });
  assert.equal(layout.visibleWidth, 600);
  assert.equal(layout.fullWidth, 1200);
  assert.equal(layout.fullHeight, 1680);
  assert.equal(layout.offsetX, 300);
});

test("crop layout without a box leaves the page alone", () => {
  assert.deepEqual(cropLayout(600, 1.4, null), {
    visibleWidth: 600,
    fullWidth: 600,
    fullHeight: 840,
    offsetX: 0,
  });
});
