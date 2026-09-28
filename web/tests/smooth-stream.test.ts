import test from "node:test";
import assert from "node:assert/strict";

import { revealGapMs, revealStep } from "../hooks/useSmoothStreamText";

/**
 * Runs a whole message through the pacing at 60fps and counts the reveals.
 *
 * Each reveal is one re-render of the consumer, and a markdown consumer
 * re-parses the entire document on each — so this count, times the length, is
 * what a turn actually costs.
 */
function costOf(
  length: number,
  charsPerFrame: number,
  { paced = true } = {},
): { reveals: number; charsParsed: number } {
  let shown = 0;
  let arrived = 0;
  let reveals = 0;
  let charsParsed = 0;
  let lastReveal = -Infinity;
  for (let frame = 0; shown < length && frame < 200_000; frame += 1) {
    const now = frame * 16.7;
    arrived = Math.min(length, arrived + charsPerFrame);
    if (paced && now - lastReveal < revealGapMs(arrived)) continue;
    const step = revealStep(shown, arrived);
    if (step === 0) continue;
    shown = Math.min(arrived, shown + step);
    lastReveal = now;
    reveals += 1;
    // One re-parse of everything revealed so far.
    charsParsed += shown;
  }
  return { reveals, charsParsed };
}

test("a short reply still types out character by character", () => {
  // The typewriter is the point at this size, and re-parsing a page of text
  // is free, so nothing is paced away.
  assert.equal(revealGapMs(200), 0);
  assert.equal(revealGapMs(1000), 0);
  // A couple of characters on the wire reveals a couple of characters; a
  // bigger backlog is caught up at a fifth of it per frame.
  assert.equal(revealStep(198, 200), 2);
  assert.equal(revealStep(100, 140), 8);
});

test("a long reply stops re-parsing itself on every frame", () => {
  // Re-rendering is what costs, and the cost of one render grows with the
  // answer — so the rate has to fall as the answer grows or the turn is
  // quadratic in its own length.
  assert.equal(revealGapMs(5000), 50); // 20fps
  assert.equal(revealGapMs(12000), 120); // the cap
  assert.equal(revealGapMs(40000), 120); // still the cap
});

test("a long answer stops paying for its own length twice", () => {
  // Three characters a frame is about what a model streams, and at that pace
  // the reveal count used to track arrival exactly: one full re-parse per
  // delta. What matters is the product — reveals times the length re-parsed
  // each time — which is what grew quadratically.
  const paced = costOf(8000, 3);
  const unpaced = costOf(8000, 3, { paced: false });
  assert.ok(
    paced.charsParsed < unpaced.charsParsed / 2,
    `pacing should more than halve the parsing work, got ${paced.charsParsed} against ${unpaced.charsParsed}`,
  );
  // The cap is what makes this hold at length; without it the ratio tends to 1.
  assert.ok(
    paced.reveals < unpaced.reveals / 2,
    `expected fewer than half the reveals, got ${paced.reveals} against ${unpaced.reveals}`,
  );
});

test("a page-length answer is left alone", () => {
  // Short messages are where the typewriter reads as a typewriter, and
  // re-parsing them is free, so pacing must not touch them at all.
  const paced = costOf(900, 3);
  const unpaced = costOf(900, 3, { paced: false });
  assert.deepEqual(paced, unpaced);
});

test("a burst still catches up rather than typing for half a minute", () => {
  // The original guarantee: 2KB landing at once is revealed by backlog/5 a
  // frame, capped — not by the per-character floor.
  assert.equal(revealStep(0, 2000), 120);
});

test("nothing is revealed once the cursor has caught up", () => {
  assert.equal(revealStep(500, 500), 0);
  assert.equal(revealStep(500, 400), 0);
});
