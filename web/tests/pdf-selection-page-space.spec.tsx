import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";
import type { AnnotationItem } from "@/lib/reading-api";

/**
 * Stored rects live in page space, not in the strip the crop leaves visible.
 *
 * Fit text (the default) draws the whole page wider than the pane and clips it
 * to the text block. `[data-reader-unit]` is that clipped strip, while marks
 * and citation flashes are painted on the full-page surface behind it — so a
 * selection normalised against the strip was stretched by the crop ratio and
 * shifted by the trimmed margin. The reviewer's numbers: a mark selected 100px
 * into the strip was stored as if it sat at 0.1667 of the page and painted
 * back at x=62, 38px left of its own text.
 *
 * Harness as in `pdf-reading-zoom.spec.tsx`: a mocked pdf.js whose page is
 * 600pt wide, a mocked ResizeObserver, and a stubbed `getBoundingClientRect`
 * for the layout jsdom does not compute. With `outputScale() = 1`, a 648px pane
 * and an ink box of 8%–92%:
 *   strip width = 648 - 48 = 600px
 *   page width  = 600 / 0.84 = 714px   (data-page-width)
 *   crop offset = 8% of 714   = 57px   (data-page-offset-x)
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
    // The page's text block covers 8%–92% of its width: Fit text draws the page
    // 714px wide (600 / 0.84) and clips 57px of it on the left.
    measurePageInkBox: async () => ({ x0: 0.08, y0: 0, x1: 0.92, y1: 1 }),
  };
});

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const GAP = 16;
const ROOT_TOP = 80;
const STRIP_LEFT = 144;
/** What the crop commits, asserted here so the maths below is readable. */
const PAGE_WIDTH = 714;
const OFFSET_X = 57;
/** A selection this far into the strip, and how wide it is. */
const SELECTION_LEFT = 100;
const SELECTION_WIDTH = 100;

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

/** The page's rendered height, in CSS pixels. */
function pageHeight(page: HTMLElement): number {
  return Number.parseFloat(page.style.height);
}

async function openReader(overrides: Partial<PdfDocumentViewProps> = {}) {
  const onSelection = vi.fn();
  const props: PdfDocumentViewProps = {
    materialId: "selection-page-space-pdf",
    unitCount: 2,
    annotations: [],
    jump: null,
    onSelection,
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  // Fit text commits the pane's width to the strip immediately; the crop lands
  // once the ink measurement has been read.
  await waitFor(() => expect(pageAt(root, 1).style.width).toBe("600px"));
  const page = pageAt(root, 1);
  await waitFor(() => expect(page.dataset.pageWidth).toBe(String(PAGE_WIDTH)));
  await act(async () => {});
  return { ...view, root, page, props, onSelection };
}

/**
 * A selection inside `page`'s text layer, `SELECTION_LEFT` px into the strip.
 *
 * Only the range's geometry is faked: the component reads the selection text,
 * its client rects and the page it started on, all of which are supplied here.
 */
function selectInside(page: HTMLElement, rect: DOMRect) {
  const layer = page.querySelector<HTMLElement>(".textLayer");
  if (!layer) throw new Error("the text layer has not mounted");
  const range = {
    commonAncestorContainer: layer,
    startContainer: layer,
    endContainer: layer,
    startOffset: 0,
    endOffset: 0,
    getClientRects: () => [rect],
    intersectsNode: () => false,
  } as unknown as Range;
  vi.spyOn(window, "getSelection").mockReturnValue({
    isCollapsed: false,
    rangeCount: 1,
    getRangeAt: () => range,
    toString: () => "the selected words",
  } as unknown as Selection);
}

function selectionRect(top: number): DOMRect {
  return new DOMRect(STRIP_LEFT + SELECTION_LEFT, top, SELECTION_WIDTH, 12);
}

function annotationWith(rects: AnnotationItem["rects"]): AnnotationItem {
  return {
    annotation_id: "page-space-1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "the selected words",
    note: "",
    rects,
    source_anchor: "",
    author: "user",
    created_at: 0,
    updated_at: 0,
  };
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
  // jsdom's Range has no geometry at all; give it an empty one so the jump's
  // range can be spied on with a real rect.
  if (typeof Range.prototype.getClientRects !== "function") {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      writable: true,
      value: () => [] as unknown as DOMRectList,
    });
  }
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
        // The strip is what the reader sees and what this rect describes.
        return new DOMRect(
          STRIP_LEFT,
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
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("PDF selection geometry in Fit text", () => {
  it("stores a strip selection in page space and paints it back over the same pixels", async () => {
    const view = await openReader();
    const { page, root } = view;
    const fullWidth = Number(page.dataset.pageWidth);
    const offsetX = Number(page.dataset.pageOffsetX);
    expect(fullWidth).toBe(PAGE_WIDTH);
    expect(offsetX).toBe(OFFSET_X);

    // 100px into the strip is 157px into the page (the 57px trimmed margin is
    // page space the strip does not show).
    const rect = selectionRect(300);
    selectInside(page, rect);
    await act(async () => {
      fireEvent.mouseUp(root);
    });

    const selection = view.onSelection.mock.calls.at(-1)?.[0] as {
      locator: number;
      rects: [number, number, number, number][];
    };
    expect(selection.locator).toBe(1);
    expect(selection.rects).toHaveLength(1);
    const [x0, y0, x1, y1] = selection.rects[0];

    // Page-space fractions — not the strip-space 0.1667/0.3333 that misplaced
    // every mark in the default mode.
    expect(x0).toBeCloseTo((SELECTION_LEFT + offsetX) / fullWidth, 6);
    expect(x1).toBeCloseTo(
      (SELECTION_LEFT + SELECTION_WIDTH + offsetX) / fullWidth,
      6,
    );
    expect(x0).not.toBeCloseTo(SELECTION_LEFT / fullWidth, 4);
    // The vertical axis has no crop, so it is unchanged.
    expect(y0).toBeCloseTo((rect.top - (ROOT_TOP + GAP)) / pageHeight(page), 6);
    expect(y1).toBeGreaterThan(y0);

    // Paint the stored rect back the way `AnnotationLayer` does and check the
    // pixels: it must land over the selection, not 38px to its left.
    view.rerender(
      <PdfDocumentView
        {...view.props}
        annotations={[annotationWith(selection.rects)]}
      />,
    );
    const mark = await waitFor(() => {
      const span = page.querySelector<HTMLElement>("span.pointer-events-auto");
      if (!span) throw new Error("the stored mark has not painted");
      return span;
    });
    // `left` is a share of the full-page surface, which starts `offsetX` to
    // the left of the strip; subtracting it gives strip pixels.
    const paintedX0 =
      (Number.parseFloat(mark.style.left) / 100) * fullWidth - offsetX;
    expect(paintedX0).toBeCloseTo(SELECTION_LEFT, 3);
    const paintedX1 =
      ((Number.parseFloat(mark.style.left) +
        Number.parseFloat(mark.style.width)) /
        100) *
        fullWidth -
      offsetX;
    expect(paintedX1).toBeCloseTo(SELECTION_LEFT + SELECTION_WIDTH, 3);
  });

  it("paints a reader_goto flash in page space too", async () => {
    const view = await openReader();
    const { page, root } = view;
    const fullWidth = Number(page.dataset.pageWidth);

    // The jump searches the rendered text layer for its quote, so give it one.
    // Wait for the page's final paint first: the text layer is rebuilt when the
    // crop commits, and a span appended before that would be wiped.
    await waitFor(() =>
      expect(
        page.querySelector<HTMLCanvasElement>("canvas")?.style.width,
      ).toBe("600px"),
    );
    const layer = page.querySelector<HTMLElement>(".textLayer")!;
    const span = document.createElement("span");
    span.textContent = "the cited words";
    layer.append(span);
    vi.spyOn(Range.prototype, "getClientRects").mockReturnValue([
      selectionRect(300),
    ] as unknown as DOMRectList);

    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 1, quote: "the cited words", nonce: 1 }}
      />,
    );

    const flash = await waitFor(
      () => {
        const element = page.querySelector<HTMLElement>(".dt-reader-flash");
        if (!element) throw new Error("the citation flash has not painted");
        return element;
      },
      { timeout: 3000 },
    );
    const paintedX0 =
      (Number.parseFloat(flash.style.left) / 100) * fullWidth - OFFSET_X;
    expect(paintedX0).toBeCloseTo(SELECTION_LEFT, 3);
    expect(root.contains(flash)).toBe(true);
  });
});
