import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";

/**
 * The crop ratio belongs to the mode that is on screen.
 *
 * Fit text draws the page wider than the pane and clips it to the text block,
 * so one zoom step starts from the size of that clipped strip. Fit page draws
 * the whole page at the pane's width — but the ratio left over from Fit text
 * used to be divided into the fit ratio anyway, so one press of "+" jumped to
 * 1250px instead of the 750px that is 1.25x the 600px on screen.
 *
 * Harness as in `pdf-reading-zoom.spec.tsx`: a mocked pdf.js whose page 1 is
 * 600pt wide, a mocked ResizeObserver, and a stubbed `getBoundingClientRect`
 * for the layout jsdom does not compute. With `outputScale() = 1` and a 648px
 * pane the numbers are:
 *   strip width = 648 - 48 = 600px
 *   100% width  = 600 * 96/72 = 800px
 *   fit ratio   = 600 / 800 = 0.75
 */

vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => 1,
  pdfjsWasmUrl: () => "/pdfjs/wasm/",
  pdfjsCMapUrl: () => "/pdfjs/cmaps/",
  loadPdfjs: async () => ({
    getDocument: () => ({
      destroy: async () => undefined,
      promise: Promise.resolve({
        getPage: async () => ({
          getViewport: ({ scale }: { scale: number }) => ({
            width: 600 * scale,
            height: 600 * 1.414 * scale,
          }),
          render: () => ({
            promise: Promise.resolve(),
            cancel: () => undefined,
          }),
          getTextContent: async () => ({ items: [] }),
          cleanup: async () => undefined,
        }),
      }),
    }),
    TextLayer: class {
      async render() {}
      cancel() {}
    },
  }),
}));

vi.mock("@/lib/pdf-page-geometry", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/pdf-page-geometry")>();
  return {
    ...actual,
    // Every page's ink covers 20%–80% of its width, so Fit text draws the page
    // 1000px wide (600 / 0.6) behind a 600px strip.
    measurePageInkBox: async () => ({ x0: 0.2, y0: 0, x1: 0.8, y1: 1 }),
  };
});

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const GAP = 16;
const ROOT_TOP = 80;
let containerWidth: number;
let viewportHeight: number;
let resizeCallbacks: Set<() => void>;

function pageTop(page: HTMLElement): number {
  let top = GAP;
  for (
    let sibling = page.previousElementSibling;
    sibling;
    sibling = sibling.previousElementSibling
  ) {
    top += Number.parseFloat((sibling as HTMLElement).style.height) + GAP;
  }
  return top;
}

function pageAt(root: HTMLElement, locator: number): HTMLElement {
  const page = root.querySelector<HTMLElement>(
    `[data-reader-unit="${locator}"]`,
  );
  if (!page) throw new Error(`Page ${locator} is missing`);
  return page;
}

/** The page's full width, of which the strip shows `visibleWidth`. */
function pageWidthOf(root: HTMLElement, locator: number): number {
  return Number(pageAt(root, locator).dataset.pageWidth);
}

async function openReader(overrides: Partial<PdfDocumentViewProps> = {}) {
  const props: PdfDocumentViewProps = {
    materialId: "fit-step-pdf",
    unitCount: 2,
    annotations: [],
    jump: null,
    onSelection: vi.fn(),
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  // Fit text always commits the pane's width to the strip.
  await waitFor(() => expect(pageAt(root, 1).style.width).toBe("600px"));
  await act(async () => {});
  return { ...view, root, props };
}

/** Pick a named stop from the zoom bar's level menu. */
async function selectZoomMode(
  view: ReturnType<typeof render>,
  label: string,
) {
  const trigger = await waitFor(() => {
    const element = view.container.querySelector<HTMLButtonElement>(
      'button[aria-haspopup="menu"]',
    );
    if (!element) throw new Error("the zoom bar has not mounted yet");
    return element;
  });
  await act(async () => {
    fireEvent.click(trigger);
  });
  const item = [
    ...view.container.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((node) => node.textContent === label);
  if (!item) throw new Error(`No "${label}" zoom mode`);
  await act(async () => {
    fireEvent.click(item);
  });
}

/** The toolbar's zoom-in / zoom-out buttons, by their accessible labels. */
function zoomButton(view: ReturnType<typeof render>, label: string) {
  const button = view.container.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  if (!button) throw new Error(`No "${label}" button`);
  return button;
}

beforeEach(() => {
  containerWidth = 648;
  viewportHeight = 500;
  resizeCallbacks = new Set();
  localStorage.clear();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        resizeCallbacks.add(this.callback);
      }
      disconnect() {
        resizeCallbacks.delete(this.callback);
      }
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("dt-reader-scroll") ? containerWidth : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.classList.contains("dt-reader-scroll")) {
        return new DOMRect(120, ROOT_TOP, containerWidth, viewportHeight);
      }
      if (this.dataset.readerUnit) {
        const root = this.closest<HTMLElement>(".dt-reader-scroll")!;
        return new DOMRect(
          144,
          ROOT_TOP + pageTop(this) - root.scrollTop,
          Number.parseFloat(this.style.width),
          Number.parseFloat(this.style.height),
        );
      }
      return new DOMRect();
    },
  );
});

afterEach(() => {
  // A debounced preference write outlives its test otherwise, and lands in the
  // next one's storage.
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("PDF reader zoom across fit modes", () => {
  it("steps from the size on screen after switching from Fit text to Fit page", async () => {
    const view = await openReader();
    // Fit text: the 60% text block fills the 600px strip, so the page behind
    // the clip is 600 / 0.6 = 1000px wide.
    await waitFor(() => expect(pageWidthOf(view.root, 1)).toBe(1000));

    await selectZoomMode(view, "Fit page");
    // Fit page: the whole page, at the strip's width.
    await waitFor(() => expect(pageWidthOf(view.root, 1)).toBe(600));

    // One press is one step from what is on screen: 75% of 800px, times 1.25,
    // is 750px. Starting from the stale 0.6 crop gave 0.75 / 0.6 * 1.25 =
    // 156%, or 1250px — past the page the reader is looking at.
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(pageWidthOf(view.root, 1)).toBe(750));
  });
});
