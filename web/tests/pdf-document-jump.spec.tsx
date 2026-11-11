import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdfDocumentView,
  type PdfDocumentViewProps,
} from "@/components/reading/PdfDocumentView";

/**
 * Citation jumps — the path a reader takes when they click a reference row and
 * the document scrolls to the cited sentence.
 *
 * The jump effect is a two-stage retry loop:
 *
 *   1. `scrollToLocator` runs on the next frame. A page that is not in the DOM
 *      yet (a jump widened the render window a frame earlier) is retried up to
 *      20 times at 120 ms.
 *   2. Once the page exists and the request carries a `quote`, the text layer
 *      is polled up to 25 times at 120 ms, starting 140 ms in. A hit turns the
 *      quote into a DOM range, normalises it against the page box, and sets
 *      `flash`, which `AnnotationLayer` paints as `dt-reader-flash` spans.
 *
 * jsdom has no layout and no `Range.getClientRects`, so this file supplies both:
 * a page-stacking model like the resize spec's, and a `getClientRects` stub that
 * turns a Range into the boxes a browser would report for it. Quote matching
 * (`domRangeForQuote`) is the real module — the assertions are on the flash
 * geometry that comes out the far end, so a wrong range, a wrong container box
 * or a wrong normalisation all show up as a wrong rect rather than as mere
 * presence.
 *
 * Text selection (`handlePointerUp`) is covered here too: it is the same
 * geometry conversion, and jsdom does support a real Selection.
 */

const pdf = vi.hoisted(() => ({
  ratios: new Map<number, number>(),
  textItems: new Map<number, string[]>(),
  /** Pages whose text layer lands *late*, after this many ms. */
  lateTextLayers: new Map<number, number>(),
  /** "error" | "string" | null — how the document load fails, if at all. */
  loadFailure: null as null | "error" | "string",
}));

const timers = new Set<number>();

function fillLayer(container: HTMLElement, items: Array<{ str: string }>) {
  container.replaceChildren(
    ...items.map((item) => {
      const span = document.createElement("span");
      span.textContent = item.str;
      return span;
    }),
  );
}

vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => 1,
  pdfjsWasmUrl: () => "/pdfjs/wasm/",
  pdfjsCMapUrl: () => "/pdfjs/cmaps/",
  loadPdfjs: async () => ({
    getDocument: () => ({
      destroy: async () => undefined,
      promise:
        pdf.loadFailure === null
          ? Promise.resolve({
              getPage: async (locator: number) => ({
                getViewport: ({ scale }: { scale: number }) => ({
                  width: 600 * scale,
                  height: 600 * (pdf.ratios.get(locator) ?? 1.414) * scale,
                }),
                render: () => ({
                  promise: Promise.resolve(),
                  cancel: () => undefined,
                }),
                getTextContent: async () => ({
                  items: (pdf.textItems.get(locator) ?? []).map((str) => ({
                    str,
                    transform: [1, 0, 0, 1, 0, 0],
                    width: 0,
                    height: 0,
                    dir: "ltr",
                    fontName: "sans-serif",
                    hasEOL: false,
                  })),
                }),
              }),
            })
          : Promise.reject(
              pdf.loadFailure === "error"
                ? new Error("worker could not open the file")
                : "the server refused the range",
            ),
    }),
    /**
     * Stands in for pdf.js' TextLayer: writes the page's runs into the
     * container as one span each, the way the real layer does. `lateTextLayers`
     * delays that write so the poll loop's "layer exists but is still filling"
     * branch is reachable — a page that was just widened into the render window.
     */
    TextLayer: class {
      private readonly container: HTMLElement;
      private readonly items: Array<{ str: string }>;
      constructor(options: {
        textContentSource: { items: Array<{ str: string }> };
        container: HTMLElement;
      }) {
        this.container = options.container;
        this.items = options.textContentSource.items;
      }
      async render() {
        const locator = Number(
          this.container.parentElement?.dataset.readerUnit,
        );
        const delay = pdf.lateTextLayers.get(locator) ?? 0;
        if (delay <= 0) {
          fillLayer(this.container, this.items);
          return;
        }
        const timer = window.setTimeout(() => {
          timers.delete(timer);
          fillLayer(this.container, this.items);
        }, delay);
        timers.add(timer);
      }
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
const ROOT_LEFT = 120;
/** Text runs start this far into the page and advance this far per character. */
const TEXT_INSET = 24;
const CHAR_WIDTH = 7;
const LINE_HEIGHT = 12;
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

function pageHeight(root: HTMLElement, locator: number): number {
  return Number.parseFloat(pageAt(root, locator).style.height);
}

function flashRects(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(".dt-reader-flash")];
}

/** The flash marks' geometry as `[left, top, width, height]` fractions. */
function flashGeometry(container: HTMLElement): number[][] {
  return flashRects(container).map((mark) => [
    Number.parseFloat(mark.style.left) / 100,
    Number.parseFloat(mark.style.top) / 100,
    Number.parseFloat(mark.style.width) / 100,
    Number.parseFloat(mark.style.height) / 100,
  ]);
}

/**
 * The boxes a browser would report for *range*.
 *
 * `startContainer`'s parent span identifies the run; its index among the page's
 * text-layer spans is the line it sits on. The box spans the selected
 * characters, so a range that resolves to the wrong offsets still produces a
 * plausible box — which is why the assertions are on the resulting geometry.
 */
function rangeToRects(range: Range): DOMRect[] {
  const start = range.startContainer;
  const parent = start.parentElement;
  const page = parent?.closest<HTMLElement>("[data-reader-unit]");
  const root = page?.closest<HTMLElement>(".dt-reader-scroll");
  if (!page || !root || !parent) return [];
  const spans = [...page.querySelectorAll<HTMLElement>(".textLayer span")];
  const line = spans.indexOf(parent);
  if (line < 0) return [];
  const chars = Math.max(1, range.endOffset - range.startOffset);
  const left = ROOT_LEFT + TEXT_INSET;
  const top = page.getBoundingClientRect().top + TEXT_INSET + line * LINE_HEIGHT;
  return [new DOMRect(left, top, CHAR_WIDTH * chars, LINE_HEIGHT)];
}

async function openReader(overrides: Partial<PdfDocumentViewProps> = {}) {
  const onSelection = vi.fn();
  const onVisibleLocatorChange = vi.fn();
  const props: PdfDocumentViewProps = {
    materialId: "jump-pdf",
    unitCount: 40,
    annotations: [],
    jump: null,
    onSelection,
    onVisibleLocatorChange,
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  let scrollTop = 0;
  // jsdom has no scrolling: model the browser's clamp from the page elements.
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
  await waitFor(() => expect(pageAt(root, 1).style.width).toBe("600px"));
  await act(async () => {});
  return { ...view, root, props, onSelection };
}

beforeEach(() => {
  containerWidth = 648;
  viewportHeight = 500;
  pdf.ratios.clear();
  pdf.textItems.clear();
  pdf.lateTextLayers.clear();
  pdf.loadFailure = null;
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
        return new DOMRect(ROOT_LEFT, ROOT_TOP, containerWidth, viewportHeight);
      }
      if (this.dataset.readerUnit) {
        const root = this.closest<HTMLElement>(".dt-reader-scroll")!;
        return new DOMRect(
          ROOT_LEFT,
          ROOT_TOP + pageTop(this) - root.scrollTop,
          Number.parseFloat(this.style.width),
          Number.parseFloat(this.style.height),
        );
      }
      return new DOMRect();
    },
  );
  // jsdom implements Range but not its geometry; without this every quote hit
  // would normalise to zero rects and the flash could never appear.
  Object.defineProperty(Range.prototype, "getClientRects", {
    configurable: true,
    value: function (this: Range) {
      return rangeToRects(this);
    },
  });
});

afterEach(() => {
  for (const timer of timers) window.clearTimeout(timer);
  timers.clear();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("jumping to a cited locator", () => {
  it("scrolls the target page to the top of the pane", async () => {
    const view = await openReader();
    expect(view.root.scrollTop).toBe(0);
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 12, nonce: 1 }} />,
    );
    // PAGE_GAP is subtracted, so the page's top edge sits under the pane's top
    // with the same breathing room the layout gives between pages.
    await waitFor(() =>
      expect(pageAt(view.root, 12).getBoundingClientRect().top).toBe(
        ROOT_TOP + GAP,
      ),
    );
    expect(view.root.scrollTop).toBeGreaterThan(0);
  });

  it("clamps a locator past the end to the last page", async () => {
    const view = await openReader();
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 999, nonce: 1 }} />,
    );
    // `Math.min(Math.max(1, jump.locator), unitCount)`: a stale citation index
    // must land on the last real page instead of a missing one — and with no
    // clamp, `scrollToLocator` would find no page at all and scroll nowhere.
    await waitFor(() =>
      expect(pageAt(view.root, 40).getBoundingClientRect().top).toBe(
        ROOT_TOP + GAP,
      ),
    );
  });

  it("clamps a locator below one to the first page", async () => {
    const view = await openReader();
    // Move away first, so "stayed at the top" cannot pass for a jump.
    view.root.scrollTop = pageTop(pageAt(view.root, 20)) + 100;
    await act(async () => {
      fireEvent.scroll(view.root);
    });
    expect(view.root.scrollTop).toBeGreaterThan(0);
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 0, nonce: 1 }} />,
    );
    await waitFor(() => expect(view.root.scrollTop).toBe(0));
  });

  it("retries the scroll while the target page is not yet in the DOM", async () => {
    const view = await openReader();
    // A jump widens the render window; the page element can be a frame late.
    // The root's `querySelector` hides page 12 for the component's first
    // lookups only — exactly the state `scrollToLocator` returning false
    // describes. Lookups made by this test go through the real method, so the
    // counter can only be advanced by the jump effect itself.
    const realQuery = view.root.querySelector.bind(view.root);
    let blocked = 0;
    const lookups: string[] = [];
    view.root.querySelector = ((selector: string) => {
      const found = realQuery(selector);
      lookups.push(selector);
      if (blocked < 2 && selector.includes('[data-reader-unit="12"]') && found) {
        blocked += 1;
        return null;
      }
      return found;
    }) as typeof view.root.querySelector;
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 12, nonce: 1 }} />,
    );
    // Wait on scroll position, not on a page lookup: the hidden lookups must
    // be the component's, not the assertion's.
    await waitFor(() => expect(view.root.scrollTop).toBeGreaterThan(0), {
      timeout: 3000,
    });
    expect(blocked).toBe(2);
    expect(
      pageAt(view.root, 12).getBoundingClientRect().top,
    ).toBe(ROOT_TOP + GAP);
  });

  it("highlights the quoted sentence once the text layer carries it", async () => {
    pdf.textItems.set(12, ["The cited sentence lives here, on page twelve."]);
    const view = await openReader();
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "cited sentence lives here", nonce: 1 }}
      />,
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(1), {
      timeout: 2000,
    });
    // Geometry, not mere presence: the flash is the matched run, normalised
    // into the page's own box. 24px inset over a 600px page; the run starts
    // 24px down an 848px page; 25 matched characters at 7px each.
    const height = pageHeight(view.root, 12);
    const [left, top, width, rectHeight] = flashGeometry(view.container)[0];
    expect(left).toBeCloseTo(TEXT_INSET / 600, 6);
    expect(top).toBeCloseTo(TEXT_INSET / height, 6);
    expect(width).toBeCloseTo((25 * CHAR_WIDTH) / 600, 6);
    expect(rectHeight).toBeCloseTo(LINE_HEIGHT / height, 6);
  });

  it("keeps polling while the text layer is still filling in", async () => {
    // The page was just widened into the render window; pdf.js fills its layer
    // a beat later. A first-poll-wins implementation gives up before the text
    // exists, so the retry has to be what makes this pass.
    pdf.lateTextLayers.set(12, 300);
    pdf.textItems.set(12, ["Late arriving words for the citation."]);
    const view = await openReader();
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "Late arriving words", nonce: 1 }}
      />,
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(1), {
      timeout: 2000,
    });
    const height = pageHeight(view.root, 12);
    const [left, top, width] = flashGeometry(view.container)[0];
    expect(left).toBeCloseTo(TEXT_INSET / 600, 6);
    expect(top).toBeCloseTo(TEXT_INSET / height, 6);
    expect(width).toBeCloseTo((19 * CHAR_WIDTH) / 600, 6);
  });

  it("still scrolls when the quote never matches", async () => {
    // A scan or an image caption: the quote is not in the layer at all. The
    // poll is bounded, and the useful half of the request — the scroll — must
    // still happen.
    pdf.textItems.set(12, ["Unrelated body text about something else."]);
    const view = await openReader();
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "absent caption words", nonce: 1 }}
      />,
    );
    await waitFor(() =>
      expect(pageAt(view.root, 12).getBoundingClientRect().top).toBe(
        ROOT_TOP + GAP,
      ),
    );
    expect(flashRects(view.container)).toHaveLength(0);
  });

  it("drops the previous highlight when a new request supersedes it", async () => {
    pdf.textItems.set(12, ["The cited sentence lives here, on page twelve."]);
    const view = await openReader();
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "cited sentence lives here", nonce: 1 }}
      />,
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(1), {
      timeout: 2000,
    });
    // The flash is tagged with the nonce that produced it, so a request
    // without a quote supersedes the old highlight instead of leaving it up.
    view.rerender(
      <PdfDocumentView {...view.props} jump={{ locator: 12, nonce: 2 }} />,
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(0));
  });

  it("fires again for a repeat of the same target under a new nonce", async () => {
    pdf.textItems.set(12, ["The cited sentence lives here, on page twelve."]);
    const view = await openReader();
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "cited sentence lives here", nonce: 1 }}
      />,
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(1), {
      timeout: 2000,
    });
    // Scroll away, then repeat the identical request: only the nonce can make
    // it fire, which is exactly why the prop carries one.
    view.root.scrollTop = 0;
    await act(async () => {
      fireEvent.scroll(view.root);
    });
    expect(view.root.scrollTop).toBe(0);
    view.rerender(
      <PdfDocumentView
        {...view.props}
        jump={{ locator: 12, quote: "cited sentence lives here", nonce: 2 }}
      />,
    );
    await waitFor(() =>
      expect(pageAt(view.root, 12).getBoundingClientRect().top).toBe(
        ROOT_TOP + GAP,
      ),
    );
    await waitFor(() => expect(flashRects(view.container)).toHaveLength(1), {
      timeout: 2000,
    });
  });
});

describe("selecting text on a page", () => {
  function selectText(
    root: HTMLElement,
    locator: number,
    text: string,
    from: number,
    to: number,
  ) {
    const layer = pageAt(root, locator).querySelector<HTMLElement>(
      ".textLayer",
    )!;
    const node = [...layer.querySelectorAll("span")]
      .map((span) => span.firstChild as Text)
      .find((candidate) => candidate?.textContent === text);
    if (!node) throw new Error(`No run "${text}" on page ${locator}`);
    const selection = window.getSelection()!;
    selection.setBaseAndExtent(node, from, node, to);
  }

  async function readerWithPageTwo() {
    pdf.textItems.set(2, ["A sentence a reader drags over."]);
    const view = await openReader();
    await waitFor(() =>
      expect(
        pageAt(view.root, 2).querySelectorAll(".textLayer span"),
      ).toHaveLength(1),
    );
    return view;
  }

  it("reports the quote, locator and normalised rects for a real selection", async () => {
    const view = await readerWithPageTwo();
    selectText(view.root, 2, "A sentence a reader drags over.", 0, 12);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    const payload = view.onSelection.mock.calls.at(-1)?.[0];
    expect(payload).toMatchObject({
      locator: 2,
      quote: "A sentence a",
    });
    // Rects are in the page's own normalised space, measured from the page
    // box rather than the viewport: 24px text inset, 12 selected characters.
    const height = pageHeight(view.root, 2);
    expect(payload.rects).toHaveLength(1);
    const [x0, y0, x1, y1] = payload.rects[0];
    expect(x0).toBeCloseTo(TEXT_INSET / 600, 6);
    expect(y0).toBeCloseTo(TEXT_INSET / height, 6);
    expect(x1 - x0).toBeCloseTo((12 * CHAR_WIDTH) / 600, 6);
    expect(y1 - y0).toBeCloseTo(LINE_HEIGHT / height, 6);
    // The popover anchor is the centre of the selection's last rect, in
    // viewport space — not the pane's, and not the page's.
    expect(payload.anchor.x).toBeCloseTo(
      ROOT_LEFT + TEXT_INSET + (12 * CHAR_WIDTH) / 2,
      6,
    );
    expect(payload.anchor.y).toBeCloseTo(
      ROOT_TOP + pageTop(pageAt(view.root, 2)) + TEXT_INSET,
      6,
    );
  });

  it("reports nothing for a collapsed selection", async () => {
    const view = await readerWithPageTwo();
    // A plain click leaves a caret behind; that is not a selection to store.
    selectText(view.root, 2, "A sentence a reader drags over.", 4, 4);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
  });

  it("reports nothing for a whitespace-only selection", async () => {
    pdf.textItems.set(2, ["A sentence a reader drags over.", " "]);
    const view = await openReader();
    await waitFor(() =>
      expect(
        pageAt(view.root, 2).querySelectorAll(".textLayer span"),
      ).toHaveLength(2),
    );
    selectText(view.root, 2, " ", 0, 1);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    // `cleanQuote` flattens it to "", and an empty quote cannot anchor a mark.
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
  });

  it("reports nothing when the selection is outside the reader", async () => {
    const view = await readerWithPageTwo();
    const outside = document.createElement("div");
    outside.textContent = "Some other text on the page";
    document.body.appendChild(outside);
    const selection = window.getSelection()!;
    selection.setBaseAndExtent(outside.firstChild!, 0, outside.firstChild!, 5);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
    outside.remove();
  });

  it("reports nothing when the selection is on no page at all", async () => {
    const view = await readerWithPageTwo();
    // The desk around the pages: inside the scroll container, outside any
    // `[data-reader-unit]`, so there is no locator to attribute it to.
    const desk = document.createElement("div");
    desk.textContent = "padding of the reader desk";
    view.root.appendChild(desk);
    const selection = window.getSelection()!;
    selection.setBaseAndExtent(desk.firstChild!, 0, desk.firstChild!, 6);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
    desk.remove();
  });

  it("reports nothing when the page carries no usable locator", async () => {
    const view = await readerWithPageTwo();
    // A page-shaped unit whose `data-reader-unit` does not parse to a locator.
    // The selection starts inside it and its geometry is perfectly usable, so
    // only the locator guard can refuse the payload — without it the mark would
    // be stored against unit 0.
    const orphan = document.createElement("div");
    orphan.dataset.readerUnit = "0";
    orphan.style.width = "600px";
    orphan.style.height = "848px";
    const layer = document.createElement("div");
    layer.className = "textLayer";
    const run = document.createElement("span");
    run.textContent = "A page with no locator at all.";
    layer.appendChild(run);
    orphan.appendChild(layer);
    pageAt(view.root, 2).parentElement!.appendChild(orphan);
    const selection = window.getSelection()!;
    selection.setBaseAndExtent(run.firstChild!, 0, run.firstChild!, 6);
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
    orphan.remove();
  });

  it("reports nothing for a selection that normalises to no rects", async () => {
    const view = await readerWithPageTwo();
    selectText(view.root, 2, "A sentence a reader drags over.", 0, 12);
    // A drag across a collapsed line reports no boxes; storing it would create
    // a mark with no visible highlight.
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => [],
    });
    await act(async () => {
      fireEvent.mouseUp(view.root);
    });
    expect(view.onSelection).toHaveBeenLastCalledWith(null);
  });
});

describe("a document that fails to open", () => {
  it("shows the loader's own message instead of the pages", async () => {
    pdf.loadFailure = "error";
    const view = render(
      <PdfDocumentView
        materialId="broken-pdf"
        unitCount={4}
        annotations={[]}
        jump={null}
        onSelection={vi.fn()}
      />,
    );
    // The whole reader is replaced: a half-rendered document beside an error
    // would let the reader select text that was never loaded.
    await waitFor(() =>
      expect(view.container.textContent).toContain(
        "This document could not be opened.",
      ),
    );
    expect(view.container.textContent).toContain(
      "worker could not open the file",
    );
    expect(view.container.querySelector(".dt-reader-scroll")).toBeNull();
  });

  it("falls back to the translated message when the failure is not an Error", async () => {
    pdf.loadFailure = "string";
    const view = render(
      <PdfDocumentView
        materialId="broken-pdf"
        unitCount={4}
        annotations={[]}
        jump={null}
        onSelection={vi.fn()}
      />,
    );
    // pdf.js rejects with plain objects for some transport failures; the
    // reader still needs a sentence to show.
    await waitFor(() =>
      expect(view.container.textContent).toContain(
        "This document could not be opened.",
      ),
    );
    expect(view.container.textContent).not.toContain(
      "the server refused the range",
    );
  });
});
