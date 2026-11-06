import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";
import { PDF_ZOOM_KEY } from "@/lib/reading-zoom";

/**
 * Zoom is derived from the same page width the resize spec drives, so this file
 * reuses that harness: a mocked pdf.js whose page 1 is 600pt wide, a mocked
 * ResizeObserver, and a stubbed `getBoundingClientRect` that gives jsdom the
 * page stacking it does not compute.
 *
 * With `outputScale() = 1` and a 648px pane the numbers are:
 *   fit width   = 648 - 48 = 600px
 *   100% width  = 600 * 96/72 = 800px
 *   fit ratio   = 600 / 800 = 0.75
 */

const pdf = vi.hoisted(() => ({
  ratios: new Map<number, number>(),
  dpr: 1,
}));

vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => pdf.dpr,
  pdfjsWasmUrl: () => "/pdfjs/wasm/",
  pdfjsCMapUrl: () => "/pdfjs/cmaps/",
  loadPdfjs: async () => ({
    getDocument: () => ({
      destroy: async () => undefined,
      promise: Promise.resolve({
        getPage: async (locator: number) => ({
          getViewport: ({ scale }: { scale: number }) => ({
            width: 600 * scale,
            height: 600 * (pdf.ratios.get(locator) ?? 1.414) * scale,
          }),
          render: () => ({
            promise: Promise.resolve(),
            cancel: () => undefined,
          }),
          getTextContent: async () => ({ items: [] }),
        }),
      }),
    }),
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

function widthOf(root: HTMLElement): number {
  return Number.parseFloat(pageAt(root, 1).style.width);
}

function positionWithin(root: HTMLElement, locator: number): number {
  const page = pageAt(root, locator);
  return (
    (root.scrollTop - pageTop(page)) / Number.parseFloat(page.style.height)
  );
}

/** Viewport x of the point `fraction` of the way across a page. */
function columnWithin(
  root: HTMLElement,
  locator: number,
  fraction: number,
): number {
  const rect = pageAt(root, locator).getBoundingClientRect();
  return rect.left + rect.width * fraction;
}

async function openReader(
  overrides: Partial<PdfDocumentViewProps> = {},
  { expectFitWidth = true }: { expectFitWidth?: boolean } = {},
) {
  const onVisibleLocatorChange = vi.fn();
  const props: PdfDocumentViewProps = {
    materialId: "zoom-pdf",
    unitCount: 160,
    annotations: [],
    jump: null,
    onSelection: vi.fn(),
    onVisibleLocatorChange,
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  let scrollTop = 0;
  // jsdom has no layout: model the browser's stacking and scroll clamp from the
  // real page elements so an anchor can be observed at all.
  Object.defineProperty(root, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      const pages = root.querySelectorAll<HTMLElement>("[data-reader-unit]");
      const last = pages[pages.length - 1];
      const contentHeight = last
        ? pageTop(last) + Number.parseFloat(last.style.height) + GAP
        : viewportHeight;
      scrollTop = Math.max(0, Math.min(value, contentHeight - viewportHeight));
    },
  });
  // jsdom computes no scrollable overflow in either direction, so the sideways
  // clamp is modelled from the widths the component commits, the same way.
  let scrollLeft = 0;
  Object.defineProperty(root, "scrollLeft", {
    configurable: true,
    get: () => scrollLeft,
    set: (value: number) => {
      const pages = root.querySelectorAll<HTMLElement>("[data-reader-unit]");
      let contentWidth = 0;
      for (const page of pages) {
        contentWidth = Math.max(
          contentWidth,
          Number.parseFloat(page.style.width) || 0,
        );
      }
      // The scroll container's own `px-6`, both sides.
      scrollLeft = Math.max(
        0,
        Math.min(value, contentWidth + 48 - containerWidth),
      );
    },
  });
  if (expectFitWidth) {
    await waitFor(() => expect(pageAt(root, 1).style.width).toBe("600px"));
  } else {
    // A stored zoom is applied on mount, so wait for any committed width.
    await waitFor(() =>
      expect(Number.parseFloat(pageAt(root, 1).style.width)).toBeGreaterThan(0),
    );
  }
  await act(async () => {});
  return { ...view, root, props };
}

async function scrollTo(root: HTMLElement, locator: number, fraction = 0.3) {
  const page = pageAt(root, locator);
  root.scrollTop =
    pageTop(page) + Number.parseFloat(page.style.height) * fraction;
  await act(async () => {
    fireEvent.scroll(root);
    await new Promise<void>((resolve) =>
      window.requestAnimationFrame(() => resolve()),
    );
  });
}

async function resize(width: number): Promise<void> {
  await act(async () => {
    containerWidth = width;
    for (const notify of resizeCallbacks) notify();
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
  pdf.dpr = 1;
  pdf.ratios.clear();
  resizeCallbacks = new Set();
  // A previous test's debounced preference write must not survive into this
  // one: it would restore a zoom the test never asked for.
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
        // The page's column moves with the pane's horizontal scroll, exactly
        // as its row moves with `scrollTop`.
        return new DOMRect(
          144 - root.scrollLeft,
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

describe("PDF reader zoom", () => {
  it("opens at fit, so the default layout is unchanged", async () => {
    const view = await openReader();
    expect(widthOf(view.root)).toBe(600);
    const control = await waitFor(() => {
      const element = view.container.querySelector('[aria-haspopup="menu"]');
      if (!element) throw new Error("zoom bar has not mounted yet");
      return element;
    });
    expect(control.textContent).toBe("Fit");
  });

  it("steps up the ladder from the ratio actually on screen", async () => {
    const view = await openReader();
    // Fitted at 75%, so one press goes to 100% = 800px, not to 25%.
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(1000));
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom out"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
  });

  it("holds the page still when the pane resizes in fixed mode", async () => {
    const view = await openReader();
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
    // Fixed is a share of the page's real size, so a wider pane must not
    // stretch it - unlike fit, which tracks the pane.
    await resize(1098);
    expect(widthOf(view.root)).toBe(800);
    // Reset returns to fit, which does track the pane: 1098 - 48 = 1050.
    await act(async () => {
      fireEvent.click(zoomButton(view, "Reset zoom"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(1050));
    await resize(648);
    await waitFor(() => expect(widthOf(view.root)).toBe(600));
  });

  it("keeps the pointer's line in place while zooming with ctrl+wheel", async () => {
    const view = await openReader();
    await scrollTo(view.root, 99, 0.3);
    const page = pageAt(view.root, 99);
    const pageRect = page.getBoundingClientRect();
    // Aim at 30% down page 99, which is what the anchor must hold.
    const pointerY = pageRect.top + pageRect.height * 0.3;
    await act(async () => {
      fireEvent.wheel(view.root, {
        ctrlKey: true,
        deltaY: -120,
        clientY: pointerY,
      });
    });
    await waitFor(() => expect(widthOf(view.root)).toBeGreaterThan(600));
    expect(positionWithin(view.root, 99)).toBeCloseTo(0.3, 1);
  });

  it("keeps the pointer's column in place while zooming sideways", async () => {
    // 200% makes the page 1600px in a 648px pane, so the pane really does
    // scroll sideways — the case where zooming used to snap back to the left
    // edge, because only the vertical axis was restored.
    localStorage.setItem(
      PDF_ZOOM_KEY,
      JSON.stringify({ mode: "fixed", scale: 2 }),
    );
    const view = await openReader({}, { expectFitWidth: false });
    await waitFor(() => expect(widthOf(view.root)).toBe(1600));
    await act(async () => {
      view.root.scrollLeft = 500;
    });
    expect(view.root.scrollLeft).toBe(500);

    const page = pageAt(view.root, 1);
    const rect = page.getBoundingClientRect();
    // Aim at 40% across and 20% down page 1.
    const pointerX = rect.left + rect.width * 0.4;
    const pointerY = rect.top + rect.height * 0.2;
    await act(async () => {
      fireEvent.wheel(view.root, {
        ctrlKey: true,
        deltaY: -120,
        clientX: pointerX,
        clientY: pointerY,
      });
    });
    await waitFor(() => expect(widthOf(view.root)).toBeGreaterThan(1600));
    // The same point of the same page must still sit under the pointer, which
    // needs `scrollLeft` restored along with `scrollTop`.
    expect(columnWithin(view.root, 1, 0.4)).toBeCloseTo(pointerX, 0);
  });

  it("holds the canvas budget per page, not only for page one", async () => {
    // Page one is landscape (ratio 0.75), page two is tall (ratio 2). Both
    // inherit the same 3200px CSS width at 400%, so page two's bitmap would be
    // 3200x6400 = 20,480,000 device pixels — past the 16.7M ceiling, which the
    // browser answers with a blank page.
    pdf.ratios.set(1, 0.75);
    pdf.ratios.set(2, 2);
    const view = await openReader();
    await act(async () => {
      fireEvent.click(
        view.container.querySelector<HTMLButtonElement>(
          'button[aria-haspopup="menu"]',
        )!,
      );
    });
    await act(async () => {
      fireEvent.click(
        view.container.querySelector<HTMLButtonElement>(
          '[role="menuitem"]:last-of-type',
        )!,
      );
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(3200));

    const painted = (locator: number) => {
      const canvas = pageAt(view.root, locator).querySelector("canvas");
      if (!canvas) throw new Error(`page ${locator} has no canvas`);
      if (canvas.style.width !== "3200px") {
        throw new Error(`page ${locator} has not repainted at 400%`);
      }
      return canvas;
    };
    const tall = await waitFor(() => painted(2));
    expect(tall.width * tall.height).toBeLessThanOrEqual(16_777_216);
    // The bitmap gives, never the layout: the CSS box stays the shared width,
    // so the column does not change size from page to page.
    expect(Number.parseFloat(tall.style.width)).toBe(3200);
    expect(Number.parseFloat(tall.style.height)).toBe(6400);
    // A page that does fit the budget keeps its full resolution.
    const first = painted(1);
    expect(first.width * first.height).toBeLessThanOrEqual(16_777_216);
    expect(first.width).toBe(3200);
  });

  it("ignores a wheel that is not a zoom gesture", async () => {
    const view = await openReader();
    await act(async () => {
      fireEvent.wheel(view.root, { deltaY: -120 });
    });
    expect(widthOf(view.root)).toBe(600);
  });

  it("reports the width it could deliver when the canvas budget clamps", async () => {
    pdf.dpr = 2;
    const view = await openReader();
    // A menu stop of 400% would be 3200px, past the budget at 2x DPR; the
    // toolbar must show what landed rather than the number that was asked for.
    await act(async () => {
      fireEvent.click(
        view.container.querySelector<HTMLButtonElement>(
          'button[aria-haspopup="menu"]',
        )!,
      );
    });
    await act(async () => {
      fireEvent.click(
        view.container.querySelector<HTMLButtonElement>(
          '[role="menuitem"]:last-of-type',
        )!,
      );
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(1722));
    expect(
      view.container.querySelector('[aria-haspopup="menu"]')?.textContent,
    ).toBe("215%");
  });

  it("writes a settled zoom once, and the next document opens at it", async () => {
    const first = await openReader();
    await act(async () => {
      fireEvent.click(zoomButton(first, "Zoom in"));
    });
    await waitFor(() => expect(widthOf(first.root)).toBe(800));
    // The write is debounced, so a drag or pinch does not hit localStorage on
    // every frame; it lands once the gesture settles.
    await waitFor(() =>
      expect(localStorage.getItem(PDF_ZOOM_KEY)).toBe(
        JSON.stringify({ mode: "fixed", scale: 1 }),
      ),
    );
    first.unmount();

    // The stored preference is read on mount, so a different document opens at
    // the remembered size rather than at fit.
    const second = await openReader(
      { materialId: "another-pdf" },
      { expectFitWidth: false },
    );
    expect(widthOf(second.root)).toBe(800);
  });

  it("restores fit from the toolbar's reset control", async () => {
    const view = await openReader();
    await act(async () => {
      fireEvent.click(zoomButton(view, "Zoom in"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
    await act(async () => {
      fireEvent.click(zoomButton(view, "Reset zoom"));
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(600));
    expect(
      view.container.querySelector('[aria-haspopup="menu"]')?.textContent,
    ).toBe("Fit");
  });

  it("keeps the keyboard shortcut alive while focus is in the zoom bar", async () => {
    const view = await openReader();
    // The bar is a sibling of the scroll root, so neither `:hover` on the root
    // nor `root.contains(activeElement)` covers it. Clicking Zoom must not make
    // ⌘+/⌘− go dead.
    const zoomIn = await waitFor(() => zoomButton(view, "Zoom in"));
    act(() => {
      zoomIn.focus();
    });
    expect(document.activeElement).toBe(zoomIn);
    await act(async () => {
      fireEvent.keyDown(window, { key: "+", metaKey: true });
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
    await act(async () => {
      fireEvent.keyDown(window, { key: "-", metaKey: true });
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(600));
  });

  it("clears its pending save and hide timers when it unmounts", async () => {
    const view = await openReader();
    const zoomIn = await waitFor(() => zoomButton(view, "Zoom in"));
    // Fake timers keep the debounce from firing while the two-pointer-move
    // sequence below re-renders 160 pages, and make the pending count exact.
    vi.useFakeTimers();
    try {
      // A zoom gesture schedules the debounced preference write (150 ms).
      await act(async () => {
        fireEvent.click(zoomIn);
      });
      expect(widthOf(view.root)).toBe(800);
      // Moving into the bottom band reveals the bar; moving out schedules its
      // hide (420 ms).
      await act(async () => {
        fireEvent.pointerMove(view.root, {
          clientY: ROOT_TOP + viewportHeight - 8,
        });
      });
      await act(async () => {
        fireEvent.pointerMove(view.root, { clientY: ROOT_TOP + 8 });
      });
      expect(vi.getTimerCount()).toBe(2);

      view.unmount();
      expect(vi.getTimerCount()).toBe(0);
      // Nothing lands in storage after the reader is gone.
      act(() => {
        vi.runAllTimers();
      });
      expect(localStorage.getItem(PDF_ZOOM_KEY)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("zooms with the keyboard only while the reader is in focus", async () => {
    const view = await openReader();
    // Without focus the chord belongs to the browser, not the reader.
    await act(async () => {
      fireEvent.keyDown(window, { key: "+", ctrlKey: true });
    });
    expect(widthOf(view.root)).toBe(600);

    view.root.focus();
    await act(async () => {
      fireEvent.keyDown(window, { key: "+", ctrlKey: true });
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(800));
    await act(async () => {
      fireEvent.keyDown(window, { key: "0", ctrlKey: true });
    });
    await waitFor(() => expect(widthOf(view.root)).toBe(600));
  });
});
