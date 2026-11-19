import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";

/**
 * The crop ratio belongs to a page, not to the render window.
 *
 * `active` holds the pages just outside the viewport, so several pages report
 * their crop at once. A single shared ratio let the last one win: here page 1's
 * text covers 60% of its width (the page behind the strip is 600 / 0.6 =
 * 1000px) and page 2's covers 90% (667px). With page 2's ratio in hand, one
 * press of "+" computed 0.75 / 0.9 * 1.25 = 104%, or 834px — it shrank the page
 * being read. Page 1's own ratio gives 0.75 / 0.6 * 1.25 = 156%, or 1250px.
 *
 * Harness as in `pdf-reading-zoom.spec.tsx`: a mocked pdf.js whose page is
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
    // Page 1's text covers 60% of its width, so Fit text draws it 1000px wide
    // (600 / 0.6) behind the 600px strip. Its neighbour's covers 90%, so the
    // same strip leaves that page 667px wide.
    measurePageInkBox: async (_page: unknown, key: string) =>
      key.endsWith(":1")
        ? { x0: 0.2, y0: 0, x1: 0.8, y1: 1 }
        : { x0: 0.05, y0: 0, x1: 0.95, y1: 1 },
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
    materialId: "adjacent-crop-pdf",
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
  localStorage.clear();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
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

describe("PDF reader zoom with a neighbour in the render window", () => {
  it("steps from the page being read, not the neighbour that reported last", async () => {
    const view = await openReader();
    // Both pages are active — page 2 is one page below the viewport, inside
    // the render margin — and each is drawn from its own text block.
    await waitFor(() => expect(pageWidthOf(view.root, 1)).toBe(1000));
    await waitFor(() => expect(pageWidthOf(view.root, 2)).toBe(667));
    // The zoom bar is dynamically imported and mounts a tick after the pages.
    await waitFor(() => expect(zoomButton(view, "Zoom in")).toBeTruthy());

    // One press is one step from page 1 on screen: 0.75 / 0.6 * 1.25 = 156%,
    // or 1250px. Page 2's 0.9 crop gave 0.75 / 0.9 * 1.25 = 104%, or 834px —
    // a "zoom in" that shrank the text the reader is looking at.
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(pageWidthOf(view.root, 1)).toBe(1250));
  });
});
