import assert from "node:assert/strict";
import test from "node:test";

import { transcriptFollowScrollTop } from "../lib/transcript-follow";

// A 400px-tall list over 4000px of cues; each row 40px. The band the active
// row may sit in without the list moving is 100px..300px of the viewport.
const list = { rowHeight: 40, viewportHeight: 400, contentHeight: 4000 };

/**
 * Where the row's centre lands on screen, given the scrollTop we chose. The
 * band is about the centre, which is why the assertions read it and not the
 * row's top edge.
 */
function viewportCentre(rowOffset: number, scrollTop: number): number {
  return rowOffset - scrollTop + list.rowHeight / 2;
}

test("a row already inside the middle band does not move the list", () => {
  // scrollTop 800 puts the row at 200px — dead centre of the band.
  const target = transcriptFollowScrollTop({
    ...list,
    rowOffset: 1000,
    currentScrollTop: 800,
  });
  assert.equal(target, 800);
});

test("a row below the band is brought to the band's lower edge, not off screen", () => {
  // scrollTop 640 puts the row at 360px, past the 300px edge.
  const target = transcriptFollowScrollTop({
    ...list,
    rowOffset: 1000,
    currentScrollTop: 640,
  });
  const landed = viewportCentre(1000, target);
  assert.ok(
    landed <= 300 && landed >= 100,
    `expected the row inside 100..300, got ${landed}`,
  );
  assert.equal(landed, 300);
});

test("a row above the band is brought to the band's upper edge", () => {
  // scrollTop 950 puts the row at 50px, above the 100px edge.
  const target = transcriptFollowScrollTop({
    ...list,
    rowOffset: 1000,
    currentScrollTop: 950,
  });
  assert.equal(viewportCentre(1000, target), 100);
});

test("early cues clamp at the top instead of scrolling past it", () => {
  const target = transcriptFollowScrollTop({
    ...list,
    rowOffset: 40,
    currentScrollTop: 0,
  });
  assert.equal(target, 0);
});

test("the last cue never scrolls past the end of the content", () => {
  const target = transcriptFollowScrollTop({
    ...list,
    rowOffset: 3960,
    currentScrollTop: 3600,
  });
  assert.equal(target, list.contentHeight - list.viewportHeight);
});

test("a short list that does not scroll stays at zero", () => {
  const target = transcriptFollowScrollTop({
    rowHeight: 40,
    viewportHeight: 400,
    contentHeight: 200,
    rowOffset: 160,
    currentScrollTop: 0,
  });
  assert.equal(target, 0);
});
