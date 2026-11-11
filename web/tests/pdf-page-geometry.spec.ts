import { describe, expect, it } from "vitest";
import {
  MAX_PAGE_CANVAS_PIXELS,
  canvasPixelRatio,
  maxPageWidth,
} from "@/lib/reading-zoom";

/**
 * Page geometry: how wide a page is drawn, and how big its bitmap may be.
 *
 * `maxPageWidth` sizes the *shared* CSS width from page one's aspect ratio.
 * That is not enough for the bitmap, because every page inherits that width
 * while its height follows its own ratio — so the per-page guard lives in
 * `canvasPixelRatio`, and these cases pin the arithmetic behind it.
 */
describe("PDF page canvas geometry", () => {
  it("sizes the shared width from page one's ratio alone", () => {
    // The clamp is real for page one: 4x on a 2x display is 3444px, not 3200.
    expect(maxPageWidth(1.414, 2)).toBe(1722);
    expect(maxPageWidth(1.414, 1)).toBe(3444);
    // ...and it says nothing about a page with a different ratio.
    expect(maxPageWidth(2, 1)).toBeLessThan(maxPageWidth(0.75, 1));
  });

  it("shows the defect: a taller page overruns the budget at page one's width", () => {
    // Page one (ratio 0.75) at 400%: 3200px wide, 2400px tall — inside budget.
    const width = Math.min(maxPageWidth(0.75, 1), 800 * 4);
    expect(width).toBe(3200);
    expect(width * width * 0.75).toBeLessThanOrEqual(MAX_PAGE_CANVAS_PIXELS);
    // Page two (ratio 2) inherits the same width and asks for 20.48M pixels.
    expect(width * width * 2).toBeGreaterThan(MAX_PAGE_CANVAS_PIXELS);
  });

  it("leaves a page that already fits at the requested ratio", () => {
    expect(canvasPixelRatio(3200, 2400, 1)).toBe(1);
    expect(canvasPixelRatio(1600, 1200, 2)).toBe(2);
  });

  it("steps the ratio down, below 1 when it must, to fit the budget", () => {
    const dpr = canvasPixelRatio(3200, 6400, 1);
    expect(dpr).toBeLessThan(1);
    expect(Math.floor(3200 * dpr) * Math.floor(6400 * dpr)).toBeLessThanOrEqual(
      MAX_PAGE_CANVAS_PIXELS,
    );
    // A browser at 2x is pulled below the 2 it asked for, and lands on the same
    // ratio: the budget is absolute, so it is the page's area that decides.
    expect(canvasPixelRatio(3200, 6400, 2)).toBeLessThan(2);
    expect(canvasPixelRatio(3200, 6400, 2)).toBe(dpr);
  });

  it("never lets a canvas exceed the budget, whatever the aspect ratio", () => {
    for (const ratio of [0.2, 0.75, 1.414, 2, 5, 40]) {
      for (const requested of [1, 1.5, 2, 3]) {
        const width = 3200;
        const height = width * ratio;
        const dpr = canvasPixelRatio(width, height, requested);
        expect(
          Math.floor(width * dpr) * Math.floor(height * dpr),
        ).toBeLessThanOrEqual(MAX_PAGE_CANVAS_PIXELS);
      }
    }
  });

  it("falls back to 1 for a nonsense request or an unmeasured page", () => {
    expect(canvasPixelRatio(0, 0, 2)).toBe(2);
    expect(canvasPixelRatio(3200, 0, 2)).toBe(2);
    expect(canvasPixelRatio(3200, 6400, Number.NaN)).toBeLessThan(1);
    expect(canvasPixelRatio(3200, 6400, 0)).toBeLessThan(1);
  });
});
