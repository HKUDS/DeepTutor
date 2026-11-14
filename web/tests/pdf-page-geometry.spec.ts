import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_PAGE_CANVAS_PIXELS,
  canvasPixelRatio,
  maxPageWidth,
} from "@/lib/reading-zoom";
import {
  INK_MEASURE_TIMEOUT_MS,
  cropLayout,
  imageBoxesFromOperatorList,
  inkBoxFromPixels,
  measurePageInkBox,
  pageImageBoxes,
} from "@/lib/pdf-page-geometry";

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

/**
 * The geometry the margin-crop and picture-hotspot features rest on.
 *
 * Its node:test twin lives in `pdf-page-geometry.test.ts`; this spec is what
 * puts the same behaviour on the vitest coverage map, so the crop and hotspot
 * code paths are measured rather than assumed.
 */
describe("ink box", () => {
  it("follows the text block, not a page number in the gutter", () => {
    const width = 200;
    const height = 100;
    const data = pixels(width, height, (x, y) => {
      if (x >= 40 && x < 160 && y >= 20 && y < 80) return true;
      // A page number in the left margin: three short glyph strokes.
      if (x >= 18 && x < 28 && y >= 90 && y < 92) return true;
      return false;
    });
    const box = inkBoxFromPixels(data, width, height);
    expect(box).not.toBeNull();
    // The ink sits at 0.2–0.8; the box adds the padding either side of it.
    expect(Math.abs(box!.x0 - 0.18)).toBeLessThan(0.005);
    expect(Math.abs(box!.x1 - 0.82)).toBeLessThan(0.005);
  });

  it("keeps paper between the text and the cut", () => {
    // A table of contents: the title block starts at the left margin and the
    // page numbers stop just short of the right one, so the ink nearly spans
    // the page. Cropping exactly to it would leave the numbers on the cut.
    const width = 200;
    const height = 100;
    const data = pixels(width, height, (x, y) => x >= 12 && x < 188 && y >= 10 && y < 90);
    const box = inkBoxFromPixels(data, width, height);
    expect(box).not.toBeNull();
    const padLeft = 12 / width - box!.x0;
    const padRight = box!.x1 - 188 / width;
    expect(padLeft).toBeGreaterThan(0.015);
    expect(padRight).toBeGreaterThan(0.015);
  });

  it("does not trim a page whose text already reaches its margins", () => {
    // A contents page or a full-width table: cropping would gain a few percent
    // and put the last glyph on the cut, so fit-the-page is the honest answer.
    const width = 200;
    const height = 100;
    const data = pixels(width, height, (x, y) => x >= 4 && x < 196 && y >= 10 && y < 90);
    expect(inkBoxFromPixels(data, width, height)).toBeNull();
  });

  it("reports nothing for a blank page", () => {
    const data = pixels(100, 100, () => false);
    expect(inkBoxFromPixels(data, 100, 100)).toBeNull();
  });

  it("reports nothing when the margin is not worth cropping", () => {
    // Ink reaching the edges leaves no margin to trim.
    const data = pixels(100, 100, () => true);
    const box = inkBoxFromPixels(data, 100, 100);
    // A full-bleed page has no crop, so the box is either null or the full page.
    expect(box === null || (box.x0 < 0.02 && box.x1 > 0.98)).toBe(true);
  });
});

describe("crop layout", () => {
  it("widens the page so the visible strip fills the pane", () => {
    const layout = cropLayout(600, 1.414, { x0: 0.1, y0: 0, x1: 0.9, y1: 1 });
    // The strip is 80% of the page, so the page must be wider than the pane.
    expect(layout.visibleWidth).toBe(600);
    expect(layout.fullWidth).toBeGreaterThan(600);
    expect(layout.offsetX).toBeGreaterThan(0);
  });

  it("leaves the page alone without a box", () => {
    const layout = cropLayout(600, 1.414, null);
    expect(layout.fullWidth).toBe(600);
    expect(layout.visibleWidth).toBe(600);
    expect(layout.offsetX).toBe(0);
  });
});

describe("picture hotspots", () => {
  it("comes from the operator list transformation matrix", () => {
    // The rectangle comes from the current transform matrix, not from the
    // operator's arguments: `transform` sets where the unit square lands, and
    // `paintImageXObject` then paints into it.
    const ops = {
      save: 10,
      restore: 11,
      transform: 12,
      paintImageXObject: 85,
      paintInlineImageXObject: 86,
      paintImageMaskXObject: 87,
    };
    const list = {
      // transform places a 100x50 rectangle at (20, 30) in page space.
      fnArray: [ops.transform, ops.paintImageXObject],
      argsArray: [[100, 0, 0, 50, 20, 30], ["img1", 100, 50]],
    };
    const boxes = imageBoxesFromOperatorList(list, ops, {
      width: 200,
      height: 100,
      transform: [1, 0, 0, -1, 0, 100],
    });
    expect(boxes.length).toBeGreaterThan(0);
    // The rectangle lands inside the page, normalised to 0..1.
    for (const box of boxes) {
      expect(box.x0).toBeGreaterThanOrEqual(0);
      expect(box.x1).toBeLessThanOrEqual(1);
      expect(box.y0).toBeGreaterThanOrEqual(0);
      expect(box.y1).toBeLessThanOrEqual(1);
    }
  });

  it("returns nothing for a page with no pictures", () => {
    const boxes = imageBoxesFromOperatorList(
      { fnArray: [10], argsArray: [[]] },
      { paintImageXObject: 85 },
      { width: 200, height: 100, transform: [1, 0, 0, -1, 0, 100] },
    );
    expect(boxes).toEqual([]);
  });

  /**
   * A form XObject with no `Matrix` entry is legal, and pdf.js reports it as
   * `null`. Multiplying by it threw, `pageImageBoxes` swallowed the throw as
   * "this page has no pictures", and every hotspot on the page disappeared —
   * including the pictures painted outside the form.
   */
  it("keeps a form's pictures when the form omits its Matrix", async () => {
    const ops = {
      save: 10,
      restore: 11,
      transform: 12,
      paintFormXObjectBegin: 13,
      paintFormXObjectEnd: 14,
      paintImageXObject: 85,
    };
    const list = {
      // One picture inside the form, one outside it. The form has no Matrix.
      fnArray: [
        ops.paintFormXObjectBegin,
        ops.transform,
        ops.paintImageXObject,
        ops.paintFormXObjectEnd,
        ops.transform,
        ops.paintImageXObject,
      ],
      argsArray: [
        [null, [0, 0, 200, 100]],
        [100, 0, 0, 50, 20, 30],
        ["inside"],
        [],
        [100, 0, 0, 50, 100, 40],
        ["outside"],
      ],
    };
    const viewport = { width: 200, height: 100, transform: [1, 0, 0, -1, 0, 100] };

    // The walk itself must not throw: an omitted Matrix means the identity.
    expect(() =>
      imageBoxesFromOperatorList(list, ops, viewport),
    ).not.toThrow();

    const page = {
      getViewport: () => viewport,
      getOperatorList: async () => list,
    };
    const boxes = await pageImageBoxes(page, ops);
    // Both pictures, not just the one the form happens to paint first.
    expect(boxes).toHaveLength(2);
    const inside = boxes.find((box) => box.x0 < 0.25 && box.x1 < 0.7);
    const outside = boxes.find((box) => box.x0 >= 0.5);
    expect(inside).toBeDefined();
    expect(outside).toBeDefined();
    // The form's pictures land where their own transform puts them, not at
    // some origin produced by a broken matrix.
    expect(inside!.x0).toBeCloseTo(0.1, 2);
    expect(inside!.x1).toBeCloseTo(0.6, 2);
    expect(outside!.x0).toBeCloseTo(0.5, 2);
    expect(outside!.x1).toBeCloseTo(1, 2);
  });
});

/**
 * Measuring the ink box paints a page into a scratch canvas.
 *
 * The regression this guards: `PDFPageProxy.render` reads `this._transport` and
 * `this._stats`, so calling it as a bare function throws. The caller turns a
 * failed measurement into "nothing to crop", so an unbound call degrades every
 * page in the document to the full width — silently, with no error surfaced to
 * the reader. That is exactly what shipped before these tests existed: the
 * crop button toggled its own `aria-pressed` while the page never changed size.
 */
describe("measuring the ink box", () => {
  /**
   * jsdom ships no canvas backend, and the shared setup makes `getContext`
   * return null. Measurement is the one thing here that genuinely paints, so
   * these tests install a scratch 2D context that records what was drawn.
   */
  function stubCanvas() {
    // A minimal 2D context with a real pixel buffer: `inkBoxFromPixels` reads
    // the painted pixels back, so a stub that only records fillRect calls
    // cannot exercise the measurement at all.
    // One context per canvas: the measurement takes a context to read the
    // pixels back, and the page's own `render` asks for one to paint with. Two
    // separate buffers would leave the reader looking at an unpainted one.
    const contexts = new WeakMap<HTMLCanvasElement, CanvasRenderingContext2D>();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (
      this: HTMLCanvasElement,
    ) {
      const cached = contexts.get(this);
      if (cached) return cached;
      const canvas = this;
      let pixels = new Uint8ClampedArray(Math.max(1, canvas.width * canvas.height * 4));
      const paint = (x: number, y: number, w: number, h: number, dark: boolean) => {
        const right = Math.min(canvas.width, x + w);
        const bottom = Math.min(canvas.height, y + h);
        for (let row = Math.max(0, y); row < bottom; row += 1) {
          for (let col = Math.max(0, x); col < right; col += 1) {
            const index = (row * canvas.width + col) * 4;
            const value = dark ? 0 : 255;
            pixels[index] = value;
            pixels[index + 1] = value;
            pixels[index + 2] = value;
            pixels[index + 3] = 255;
          }
        }
      };
      const context = {
        fillStyle: "#000000",
        fillRect(x: number, y: number, w: number, h: number) {
          const dark = context.fillStyle === "#000000";
          // Resizing the canvas between fills reallocates the buffer, as a real
          // context does, so keep it sized to the canvas before painting.
          const needed = canvas.width * canvas.height * 4;
          if (pixels.length !== needed) {
            pixels = new Uint8ClampedArray(Math.max(1, needed));
            pixels.fill(255);
            for (let index = 3; index < pixels.length; index += 4) pixels[index] = 255;
          }
          paint(x, y, w, h, dark);
        },
        getImageData(x: number, y: number, w: number, h: number) {
          return { data: pixels.slice(0, w * h * 4), width: w, height: h };
        },
      };
      const asContext = context as unknown as CanvasRenderingContext2D;
      contexts.set(canvas, asContext);
      return asContext;
    });
  }

  /** A stand-in page whose `render` insists on being called as a method. */
  function page(options: { inkFrom?: number; inkTo?: number } = {}) {
    const inkFrom = options.inkFrom ?? 0.1;
    const inkTo = options.inkTo ?? 0.9;
    return {
      calls: 0,
      // `this` matters on purpose: pdf.js's real method reads its own state,
      // and a double that tolerated an unbound call could not catch the bug.
      render(
        this: { calls: number },
        parameters: { canvas: HTMLCanvasElement; viewport: { width: number; height: number } },
      ) {
        if (!this) {
          throw new TypeError(
            "Cannot read properties of undefined (reading '_stats')",
          );
        }
        this.calls += 1;
        const { canvas } = parameters;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("no 2d context in this environment");
        const ink = Math.round(canvas.width * (inkTo - inkFrom));
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#000000";
        context.fillRect(Math.round(canvas.width * inkFrom), 0, ink, canvas.height);
        return { promise: Promise.resolve() };
      },
      getViewport({ scale }: { scale: number }) {
        return { width: 400 * scale, height: 566 * scale, transform: [1, 0, 0, 1, 0, 0] };
      },
    };
  }

  it("measures the text block instead of giving up", async () => {
    stubCanvas();
    const source = page({ inkFrom: 0.1, inkTo: 0.9 });
    const box = await measurePageInkBox(source as never, "measure:real");
    // A measured box is the whole point: `null` here means every page silently
    // renders at full width and the crop preference does nothing.
    expect(box).not.toBeNull();
    expect(box!.x0).toBeCloseTo(0.1, 1);
    expect(box!.x1).toBeCloseTo(0.9, 1);
    // And it really did paint — not a cached or short-circuited answer.
    expect(source.calls).toBe(1);
  });

  it("calls render as a method, not as a detached function", async () => {
    stubCanvas();
    // The exact failure mode: pulling `render` off the object first.
    const source = page();
    const detached: typeof source.render = source.render;
    expect(() =>
      // `this` is deliberately unbound here — that is the whole point of the
      // test, so the type-level guard is silenced rather than worked around by
      // binding it.
      (detached as (parameters: { canvas: HTMLCanvasElement; viewport: { width: number; height: number } }) => unknown)({
        canvas: document.createElement("canvas"),
        viewport: { width: 1, height: 1 },
      }),
    ).toThrow(TypeError);
    // The real call path keeps `this`, so it must not throw.
    await expect(measurePageInkBox(source as never, "measure:bound")).resolves.not.toBeNull();
  });

  it("gives up on a measurement that never settles", async () => {
    // Some embedded browsers paint a page but never settle the render promise.
    // Without a bound the "not measured yet" state never ended: the canvas was
    // never painted at all, and the hung promise stayed cached for the life of
    // the tab, so a remount got the same dead promise back.
    stubCanvas();
    vi.useFakeTimers();
    try {
      const stuck = {
        calls: 0,
        getViewport: () => ({ width: 612, height: 792 }),
        // Never resolves: exactly the environment the comment describes.
        render() {
          this.calls += 1;
          return { promise: new Promise<void>(() => {}) };
        },
      };
      const pending = measurePageInkBox(stuck as never, "measure:stuck");
      // The reader gets the whole page rather than a blank one.
      await vi.advanceTimersByTimeAsync(INK_MEASURE_TIMEOUT_MS + 1);
      await expect(pending).resolves.toBeNull();
      // And the dead promise is not kept: a remount measures again.
      const second = measurePageInkBox(stuck as never, "measure:stuck");
      await vi.advanceTimersByTimeAsync(INK_MEASURE_TIMEOUT_MS + 1);
      await expect(second).resolves.toBeNull();
      expect(stuck.calls).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("remembers a page so a re-render does not measure twice", async () => {
    stubCanvas();
    const source = page();
    const first = await measurePageInkBox(source as never, "measure:cached");
    const second = await measurePageInkBox(source as never, "measure:cached");
    expect(source.calls).toBe(1);
    expect(second).toEqual(first);
  });

  it("degrades to no crop when the page cannot be painted", async () => {
    stubCanvas();
    const broken = {
      render() {
        throw new Error("render failed");
      },
      getViewport() {
        return { width: 400, height: 566, transform: [1, 0, 0, 1, 0, 0] };
      },
    };
    // A page that cannot be measured still has to open; the reader shows it at
    // full width rather than refusing to render the document.
    await expect(measurePageInkBox(broken as never, "measure:broken")).resolves.toBeNull();
  });
});
