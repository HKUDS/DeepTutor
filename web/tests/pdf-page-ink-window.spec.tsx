import { act, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfPage, type PdfPageProps } from "@/components/reading/PdfPage";
import type { PdfDocument } from "@/lib/pdfjs-loader";

/**
 * The ink measurement and the picture measurement are both parses, and both
 * must stay inside the render window.
 *
 * `PdfDocumentView` mounts one `PdfPage` per locator, so measuring on mount
 * started 600 scratch renders and read 600 operator lists the moment a
 * 600-page document opened. The visible page still has to be measured, because
 * its crop is what Fit text draws and its hotspots are what the reader clicks.
 */

/** The operator ids the picture walk needs; pdf.js's real ones are opaque. */
const { OPS } = vi.hoisted(() => ({
  OPS: {
    save: 10,
    restore: 11,
    transform: 12,
    paintFormXObjectBegin: 13,
    paintFormXObjectEnd: 14,
    paintImageXObject: 85,
  },
}));

vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => 1,
  loadPdfjs: async () => ({
    OPS,
    TextLayer: class {
      async render() {}
      cancel() {}
    },
  }),
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

/**
 * jsdom ships no canvas backend, and the shared setup makes `getContext`
 * return null. Measurement is the one thing here that genuinely paints, so
 * install a scratch 2D context with a real pixel buffer for it to read back.
 */
function stubCanvas() {
  const contexts = new WeakMap<HTMLCanvasElement, CanvasRenderingContext2D>();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    const cached = contexts.get(this);
    if (cached) return cached;
    const canvas = this;
    let pixels = new Uint8ClampedArray(
      Math.max(1, canvas.width * canvas.height * 4),
    );
    const resize = () => {
      const needed = Math.max(1, canvas.width * canvas.height * 4);
      if (pixels.length === needed) return;
      pixels = new Uint8ClampedArray(needed);
      pixels.fill(255);
      for (let index = 3; index < pixels.length; index += 4) pixels[index] = 255;
    };
    resize();
    const context = {
      fillStyle: "#ffffff",
      fillRect(x: number, y: number, w: number, h: number) {
        resize();
        const dark = context.fillStyle !== "#ffffff";
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

interface Calls {
  getPage: number;
  /** The 200px scratch render `measurePageInkBox` paints. */
  scratch: number;
  /** The page's own canvas. */
  visible: number;
  /** Reads of the operator list the picture hotspots come from. */
  operators: number;
  cleanup: number;
  /** Viewport width of every page-canvas paint, in order. */
  widths: number[];
}

/** A page 600pt wide whose text block covers `inkLeft`–`inkLeft+inkWidth`. */
function pageDocument({ inkLeft = 0.2, inkWidth = 0.6 } = {}) {
  const calls: Calls = {
    getPage: 0,
    scratch: 0,
    visible: 0,
    operators: 0,
    cleanup: 0,
    widths: [],
  };
  const page = {
    render(
      this: unknown,
      parameters: {
        canvas: HTMLCanvasElement;
        viewport: { width: number; height: number };
      },
    ) {
      const { canvas, viewport } = parameters;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no 2d context in this environment");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#000000";
      context.fillRect(
        Math.round(canvas.width * inkLeft),
        0,
        Math.round(canvas.width * inkWidth),
        canvas.height,
      );
      if (viewport.width <= 200.5) {
        calls.scratch += 1;
      } else {
        calls.visible += 1;
        calls.widths.push(viewport.width);
      }
      return { promise: Promise.resolve(), cancel: () => undefined };
    },
    getViewport({ scale }: { scale: number }) {
      return {
        width: 600 * scale,
        height: 849 * scale,
        transform: [1, 0, 0, 1, 0, 0],
      };
    },
    getTextContent: async () => ({ items: [] }),
    // One picture covering the top-left tenth of the page, so an in-window
    // page gets a hotspot and the operator read has a visible result.
    getOperatorList: async () => {
      calls.operators += 1;
      return {
        fnArray: [OPS.transform, OPS.paintImageXObject],
        argsArray: [[100, 0, 0, 50, 20, 30], ["img"]],
      };
    },
    cleanup: async () => {
      calls.cleanup += 1;
    },
  };
  const doc = {
    getPage: async () => {
      calls.getPage += 1;
      return page;
    },
  };
  return { doc: doc as unknown as PdfDocument, calls };
}

const base = {
  locator: 7,
  width: 600,
  fallbackRatio: 1.414,
  annotations: [],
  cropMargins: true,
} satisfies Omit<PdfPageProps, "doc" | "active" | "retain" | "inkKey">;

/** Let every effect (and the microtasks behind them) run. */
async function settle() {
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 20));
  });
}

describe("PDF page ink measurement window", () => {
  it("does not scratch-render a page outside it", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    render(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain={false}
        inkKey="ink-window:inactive"
      />,
    );
    await settle();
    // Not even parsed: a page far from the viewport must not start pdf.js work.
    expect(calls.getPage).toBe(0);
    expect(calls.scratch).toBe(0);
    expect(calls.operators).toBe(0);
  });

  it("still measures the active page and crops to its ink", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    const view = render(
      <PdfPage {...base} doc={doc} active retain inkKey="ink-window:active" />,
    );
    const page = view.container.querySelector<HTMLElement>("[data-reader-unit]")!;

    await waitFor(() => expect(calls.scratch).toBe(1));
    // The sample is the 200px scratch render; the page's own canvas is painted
    // at the committed width — and only once, after the crop is known.
    await waitFor(() => expect(calls.visible).toBe(1));

    // Ink covers 60% of the page plus the 2% of paper kept either side, so the
    // full page is 600 / 0.64 = 938px wide and the strip starts at 18% of it.
    await waitFor(() => expect(Number(page.dataset.pageWidth)).toBe(938));
    expect(Number(page.dataset.pageOffsetX)).toBe(169);
    // Exactly one paint, and at the cropped viewport — not the old
    // `[600, 938]` pair of an uncropped draw followed by the real one.
    await settle();
    expect(calls.visible).toBe(1);
    expect(calls.widths).toHaveLength(1);
    expect(calls.widths[0]).toBeCloseTo(938, 6);
    // The strip itself is still the pane's width: measuring must not change
    // what the reader sees.
    expect(page.style.width).toBe("600px");
  });

  it("paints a page with nothing to crop exactly once", async () => {
    stubCanvas();
    // Ink covers 98% of the page — past MAX_CONTENT_WIDTH, so the measurement
    // answers "nothing to crop". The layout is then the same before and after
    // measuring, which is exactly the case where an unmeasured page and a
    // measured one used to be indistinguishable: the page was painted once
    // while waiting and once when the answer arrived.
    const { doc, calls } = pageDocument({ inkLeft: 0.01, inkWidth: 0.98 });
    const view = render(
      <PdfPage
        {...base}
        doc={doc}
        active
        retain
        inkKey="ink-window:no-crop"
      />,
    );
    const page = view.container.querySelector<HTMLElement>("[data-reader-unit]")!;

    await waitFor(() => expect(calls.scratch).toBe(1));
    await waitFor(() => expect(calls.visible).toBe(1));
    // And nothing repaints once the measurement has settled.
    await settle();
    expect(calls.visible).toBe(1);
    expect(Number(page.dataset.pageWidth)).toBe(600);
    expect(Number(page.dataset.pageOffsetX)).toBe(0);
  });

  it("hands back a page that was measured but never painted", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    const view = render(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain
        inkKey="ink-window:released"
      />,
    );
    await waitFor(() => expect(calls.scratch).toBe(1));
    expect(calls.visible).toBe(0);

    // The page leaves the retained window without ever having drawn a canvas.
    view.rerender(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain={false}
        inkKey="ink-window:released"
      />,
    );
    await waitFor(() => expect(calls.cleanup).toBeGreaterThanOrEqual(1));
  });
});

describe("PDF page picture measurement window", () => {
  it("does not read a page's operator list outside the window", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    render(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain={false}
        cropMargins={false}
        inkKey="picture-window:inactive"
      />,
    );
    await settle();
    // Reading 600 operator lists on open was the whole cost of this defect.
    expect(calls.getPage).toBe(0);
    expect(calls.operators).toBe(0);
  });

  it("reads the operators once for a page inside the window", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    const onImageClick = vi.fn();
    const view = render(
      <PdfPage
        {...base}
        doc={doc}
        active
        retain
        cropMargins={false}
        inkKey="picture-window:active"
        onImageClick={onImageClick}
      />,
    );
    await waitFor(() => expect(calls.operators).toBe(1));
    // The measurement reaches the DOM: the picture is a clickable hotspot.
    const hotspot = await view.findByLabelText("Zoom image");
    expect(hotspot).toBeTruthy();
    expect(onImageClick).not.toHaveBeenCalled();
  });

  it("hands back a page measured only for its pictures", async () => {
    stubCanvas();
    const { doc, calls } = pageDocument();
    const view = render(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain
        cropMargins={false}
        inkKey="picture-window:released"
      />,
    );
    // Parsed for its pictures, never painted: no canvas work at all.
    await waitFor(() => expect(calls.operators).toBe(1));
    expect(calls.visible).toBe(0);

    // The page leaves the retained window without ever having drawn a canvas.
    view.rerender(
      <PdfPage
        {...base}
        doc={doc}
        active={false}
        retain={false}
        cropMargins={false}
        inkKey="picture-window:released"
      />,
    );
    await waitFor(() => expect(calls.cleanup).toBeGreaterThanOrEqual(1));
  });
});
