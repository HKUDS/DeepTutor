import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  MAX_PREVIEW_CANVAS_AXIS,
  PdfImageZoomOverlay,
  previewCanvasPlan,
} from "@/components/reading/PdfImageZoomOverlay";
import { MAX_PAGE_CANVAS_PIXELS } from "@/lib/reading-zoom";

/**
 * The picture preview's bitmap budget.
 *
 * The preview sizes its canvas from the picture's width alone, so a picture
 * that is 2% of the page width and full page height — legal, since it passes
 * the 0.3% hotspot area threshold — asked for a bitmap about 1679x111957
 * device pixels on a 1024px window at DPR 2: roughly 188M pixels, 717MiB of
 * RGBA. The page reader's own budget is 16,777,216 device pixels, and no
 * canvas is useful past a few thousand pixels on one side. Opening the preview
 * has to scale that picture down, not refuse it and not hand the browser a
 * bitmap it will drop.
 */

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

// A 2x display, which is where the reported allocation came from.
vi.mock("@/lib/pdfjs-loader", () => ({ outputScale: () => 2 }));

const PAGE = { width: 600, height: 800 };

function pageDocument() {
  return {
    getPage: async () => ({
      getViewport: ({ scale }: { scale: number }) => ({
        width: PAGE.width * scale,
        height: PAGE.height * scale,
      }),
      render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
    }),
  };
}

/** Mounts the preview and returns its canvas once the paint has settled. */
async function preview(box: { x0: number; y0: number; x1: number; y1: number }) {
  const view = render(
    <PdfImageZoomOverlay
      doc={pageDocument() as never}
      locator={1}
      box={box}
      onClose={() => {}}
    />,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  const canvas = view.container.querySelector("canvas");
  expect(canvas).not.toBeNull();
  return canvas!;
}

/** The picture's own aspect ratio, as the page draws it. */
const aspect = (box: { x0: number; y0: number; x1: number; y1: number }) =>
  ((box.x1 - box.x0) * PAGE.width) / ((box.y1 - box.y0) * PAGE.height);

describe("picture preview bitmap budget", () => {
  it("caps a 2%-wide full-height picture at both limits", async () => {
    const box = { x0: 0, y0: 0, x1: 0.02, y1: 1 };
    const canvas = await preview(box);

    expect(canvas.width * canvas.height).toBeLessThanOrEqual(
      MAX_PAGE_CANVAS_PIXELS,
    );
    expect(canvas.width).toBeLessThanOrEqual(MAX_PREVIEW_CANVAS_AXIS);
    expect(canvas.height).toBeLessThanOrEqual(MAX_PREVIEW_CANVAS_AXIS);
    // The reported bitmap was 111957 device pixels tall; the cap has to bite
    // on the axis, not merely on the total.
    expect(canvas.height).toBeLessThan(111_957);
    // And the picture is still there: scaling down must not collapse it to a
    // one-pixel strip.
    expect(canvas.width).toBeGreaterThan(0);
    expect(canvas.height).toBeGreaterThan(0);
  });

  it("keeps the tall picture's natural aspect rather than stretching it", async () => {
    const box = { x0: 0, y0: 0, x1: 0.02, y1: 1 };
    const canvas = await preview(box);
    expect(canvas.width / canvas.height).toBeCloseTo(aspect(box), 2);
    // The CSS box follows the bitmap, so the picture is sharp at 1:1 instead
    // of a stretched thumbnail.
    expect(parseFloat(canvas.style.width)).toBeCloseTo(canvas.width / 2, 0);
    expect(parseFloat(canvas.style.height)).toBeCloseTo(canvas.height / 2, 0);
  });

  it("renders a normal picture whole, at full resolution", async () => {
    const box = { x0: 0.1, y0: 0.2, x1: 0.6, y1: 0.5 };
    const canvas = await preview(box);

    // The preview opens the picture *whole*: the stage is 86% of the jsdom
    // window wide and 72% of it tall, so a 300x240 picture is limited by
    // height, not stretched to the full width.
    const cssWidth = parseFloat(canvas.style.width);
    const cssHeight = parseFloat(canvas.style.height);
    expect(cssWidth).toBeLessThanOrEqual(1024 * 0.86);
    expect(cssHeight).toBeLessThanOrEqual(768 * 0.72);
    expect(cssWidth / cssHeight).toBeCloseTo(aspect(box), 2);
    // Full device resolution for whatever CSS box was chosen.
    expect(canvas.width).toBe(Math.floor(cssWidth * 2));
    expect(canvas.height).toBe(Math.floor(cssHeight * 2));
    expect(canvas.width * canvas.height).toBeLessThan(
      MAX_PAGE_CANVAS_PIXELS / 4,
    );
    expect(canvas.height).toBeLessThan(MAX_PREVIEW_CANVAS_AXIS);
  });

  it("never exceeds either cap, whatever the picture's shape", () => {
    for (const [width, height] of [
      [12, 800], // 2% of the page width, full height
      [12, 120], // a narrow, tall figure
      [1, 800], // thinner still
      [600, 1], // a wide rule
      [600, 800], // a full-page scan
      [300, 240], // an ordinary figure
    ]) {
      for (const dpr of [1, 1.5, 2, 3]) {
        const plan = previewCanvasPlan(width, height, 70, dpr);
        expect(plan.width).toBeGreaterThan(0);
        expect(plan.height).toBeGreaterThan(0);
        expect(plan.width).toBeLessThanOrEqual(MAX_PREVIEW_CANVAS_AXIS);
        expect(plan.height).toBeLessThanOrEqual(MAX_PREVIEW_CANVAS_AXIS);
        expect(plan.width * plan.height).toBeLessThanOrEqual(
          MAX_PAGE_CANVAS_PIXELS,
        );
        // The rendered CSS box matches the bitmap's resolution.
        expect(plan.width).toBe(Math.floor(plan.cssWidth * dpr));
        expect(plan.height).toBe(Math.floor(plan.cssHeight * dpr));
      }
    }
  });

  it("leaves a request inside both caps untouched", () => {
    const plan = previewCanvasPlan(300, 240, 2.5, 2);
    expect(plan.scale).toBe(2.5);
    expect(plan.cssWidth).toBe(750);
    expect(plan.cssHeight).toBe(600);
    expect(plan.width).toBe(1500);
    expect(plan.height).toBe(1200);
  });
});

describe("a picture opens whole", () => {
  it("fits a full-page scan to the stage instead of showing its middle", () => {
    // One full-page image hotspot: 600x800pt page, the whole page is the
    // picture, the stage is a 1440x900 window net of padding and toolbar.
    const stage = { width: 1240, height: 760 };
    const plan = previewCanvasPlan(600, 800, 2.689, 2, stage);
    expect(plan.cssHeight).toBeLessThanOrEqual(stage.height);
    expect(plan.cssWidth).toBeLessThanOrEqual(stage.width);
    // And it keeps the picture's aspect, so nothing is squashed.
    expect(plan.cssWidth / plan.cssHeight).toBeCloseTo(600 / 800, 2);
  });

  it("leaves a picture that already fits alone", () => {
    const stage = { width: 1240, height: 760 };
    const plan = previewCanvasPlan(300, 240, 1.5, 2, stage);
    // 300x240 at 1.5x is 450x360 CSS, inside the stage: untouched.
    expect(plan.cssWidth).toBe(450);
    expect(plan.cssHeight).toBe(360);
  });
});
