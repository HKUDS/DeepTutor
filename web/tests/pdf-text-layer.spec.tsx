import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PdfPage } from "@/components/reading/PdfPage";
import type { PdfDocument } from "@/lib/pdfjs-loader";

const pdf = vi.hoisted(() => ({
  cleanupCalls: 0,
  getPageCalls: 0,
  getTextContentCalls: 0,
  outputScale: 1,
  renderCalls: 0,
  renderGate: null as Promise<void> | null,
  renderWidths: [] as number[],
  textLayerGate: null as Promise<void> | null,
  textLayerConstructions: 0,
  textLayerRenders: 0,
}));

vi.mock("@/lib/pdfjs-loader", () => ({
  outputScale: () => pdf.outputScale,
  loadPdfjs: async () => ({
    TextLayer: class {
      private readonly container: HTMLElement;

      constructor({ container }: { container: HTMLElement }) {
        pdf.textLayerConstructions += 1;
        this.container = container;
        this.container.style.width = "600px";
        this.container.style.height = "800px";
        this.container.style.setProperty("--min-font-size", "1");
        this.container.dataset.mainRotation = "0";
      }

      async render() {
        pdf.textLayerRenders += 1;
        await pdf.textLayerGate;
        const span = document.createElement("span");
        span.textContent = "retained text";
        this.container.append(span);
      }

      cancel() {}
    },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const page = {
  cleanup: () => {
    pdf.cleanupCalls += 1;
  },
  getTextContent: async () => {
    pdf.getTextContentCalls += 1;
    return { items: [], styles: {} };
  },
  getViewport: ({ scale }: { scale: number }) => ({
    height: 800 * scale,
    rotation: 0,
    scale,
    width: 600 * scale,
  }),
  render: ({ viewport }: { viewport: { width: number } }) => {
    pdf.renderCalls += 1;
    pdf.renderWidths.push(viewport.width);
    return {
      cancel: () => undefined,
      promise: pdf.renderGate ?? Promise.resolve(),
    };
  },
};

const doc = {
  getPage: async () => {
    pdf.getPageCalls += 1;
    return page;
  },
} as unknown as PdfDocument;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function element({
  document = doc,
  active = true,
  retain = true,
  width = 600,
}: {
  document?: PdfDocument;
  active?: boolean;
  retain?: boolean;
  width?: number;
} = {}) {
  return (
    <PdfPage
      doc={document}
      locator={1}
      width={width}
      fallbackRatio={4 / 3}
      active={active}
      retain={retain}
      annotations={[]}
    />
  );
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  pdf.cleanupCalls = 0;
  pdf.getPageCalls = 0;
  pdf.getTextContentCalls = 0;
  pdf.outputScale = 1;
  pdf.renderCalls = 0;
  pdf.renderGate = null;
  pdf.renderWidths = [];
  pdf.textLayerGate = null;
  pdf.textLayerConstructions = 0;
  pdf.textLayerRenders = 0;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PdfPage rendering lifecycle", () => {
  it("builds selectable text without waiting for the visible bitmap", async () => {
    const renderGate = deferred<void>();
    pdf.renderGate = renderGate.promise;
    const view = render(element());

    await waitFor(() => expect(pdf.renderCalls).toBe(1));
    await waitFor(() => expect(pdf.getTextContentCalls).toBe(1));
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );

    await act(async () => {
      renderGate.resolve();
      await renderGate.promise;
    });
  });

  it("renders the first bitmap at the final device scale", async () => {
    pdf.outputScale = 2;
    const view = render(element());

    await waitFor(() => expect(pdf.renderCalls).toBe(1));
    expect(view.container.querySelector("canvas")!.width).toBe(1200);
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    await flushEffects();
    expect(pdf.renderCalls).toBe(1);
  });

  it("reuses one text layer and its nodes across width changes", async () => {
    const view = render(element());
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    const originalSpan = view.container.querySelector(".textLayer span");

    view.rerender(element({ width: 700 }));
    view.rerender(element({ width: 800 }));
    await flushEffects();

    expect(view.container.querySelector(".textLayer span")).toBe(originalSpan);
    expect(pdf.getTextContentCalls).toBe(1);
    expect(pdf.textLayerConstructions).toBe(1);
    expect(pdf.textLayerRenders).toBe(1);
  });

  it("drops inactive text nodes and rebuilds them when the page returns", async () => {
    const view = render(element());
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    const originalSpan = view.container.querySelector(".textLayer span");

    view.rerender(element({ active: false, retain: true }));
    expect(view.container.querySelector(".textLayer span")).toBeNull();
    view.rerender(element({ active: true, retain: true }));
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );

    expect(view.container.querySelector(".textLayer span")).not.toBe(originalSpan);
    expect(pdf.getTextContentCalls).toBe(2);
  });

  it("does not acquire an untouched page only because it is retained", async () => {
    render(element({ active: false, retain: true }));
    await flushEffects();

    expect(pdf.getPageCalls).toBe(0);
  });

  it("repaints once at the final width after resize settles", async () => {
    const view = render(element());
    await waitFor(() => expect(pdf.renderCalls).toBe(1));
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    vi.useFakeTimers();

    view.rerender(element({ width: 700 }));
    view.rerender(element({ width: 800 }));
    await flushEffects();
    expect(pdf.renderCalls).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(149);
    });
    expect(pdf.renderCalls).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(pdf.renderCalls).toBe(2);
    expect(pdf.renderWidths).toEqual([600, 800]);
  });

  it("releases the previous page and repaints when the document changes at the same width", async () => {
    const firstCleanup = vi.fn();
    const secondCleanup = vi.fn();
    const firstPage = { ...page, cleanup: firstCleanup };
    const secondPage = { ...page, cleanup: secondCleanup };
    const firstDocument = {
      getPage: async () => firstPage,
    } as unknown as PdfDocument;
    const secondDocument = {
      getPage: async () => secondPage,
    } as unknown as PdfDocument;

    const view = render(element({ document: firstDocument }));
    await waitFor(() => expect(pdf.renderCalls).toBe(1));
    view.rerender(element({ document: secondDocument }));
    await waitFor(() => expect(pdf.renderCalls).toBe(2));

    expect(firstCleanup).toHaveBeenCalledTimes(1);
    expect(secondCleanup).not.toHaveBeenCalled();
  });

  it("contains synchronous page setup failures inside the page error state", async () => {
    const brokenPage = {
      ...page,
      getViewport: () => {
        throw new Error("broken viewport");
      },
    };
    const brokenDocument = {
      getPage: async () => brokenPage,
    } as unknown as PdfDocument;

    const view = render(element({ document: brokenDocument }));

    await waitFor(() =>
      expect(
        view.getByText("This page could not be rendered."),
      ).toBeInTheDocument(),
    );
  });

  it("keeps usable text when canvas task creation fails synchronously", async () => {
    const brokenCanvasPage = {
      ...page,
      render: () => {
        throw new Error("broken canvas");
      },
    };
    const brokenDocument = {
      getPage: async () => brokenCanvasPage,
    } as unknown as PdfDocument;

    const view = render(element({ document: brokenDocument }));

    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    expect(
      view.queryByText("This page could not be rendered."),
    ).not.toBeInTheDocument();
  });

  it("publishes the visible bitmap without waiting for deferred text", async () => {
    const textGate = deferred<void>();
    pdf.textLayerGate = textGate.promise;
    const view = render(element());

    await waitFor(() => expect(pdf.renderCalls).toBe(1));
    await waitFor(() => expect(pdf.textLayerRenders).toBe(1));
    expect(view.container.querySelector(".textLayer span")).toBeNull();

    textGate.resolve();
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
  });

  it("releases canvas, text nodes, and page resources outside retention", async () => {
    const view = render(element());
    await waitFor(() =>
      expect(view.container.querySelector(".textLayer span")).not.toBeNull(),
    );
    const textLayer = view.container.querySelector<HTMLElement>(".textLayer")!;
    expect(textLayer.style.width).toBe("600px");
    expect(textLayer.dataset.mainRotation).toBe("0");

    view.rerender(element({ active: false, retain: false }));

    await waitFor(() => expect(pdf.cleanupCalls).toBe(1));
    expect(textLayer.childNodes).toHaveLength(0);
    const canvas = view.container.querySelector("canvas")!;
    expect(canvas.width).toBe(0);
    expect(canvas.height).toBe(0);
  });

  it("cancels an in-flight canvas render when the page turns off", async () => {
    const renderGate = deferred<void>();
    const cancel = vi.fn();
    const slowPage = {
      ...page,
      render: () => ({ cancel, promise: renderGate.promise }),
    };
    const slowDocument = {
      getPage: async () => slowPage,
    } as unknown as PdfDocument;
    const view = render(element({ document: slowDocument }));
    await waitFor(() =>
      expect(view.container.querySelector("canvas")!.width).toBe(600),
    );

    view.rerender(
      element({ document: slowDocument, active: false, retain: true }),
    );

    await waitFor(() => expect(cancel).toHaveBeenCalledTimes(1));
    renderGate.resolve();
  });
});
