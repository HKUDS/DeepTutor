import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfDocumentView, type PdfDocumentViewProps } from "@/components/reading/PdfDocumentView";

/**
 * The pointer and focus behaviour of the reading surface itself.
 *
 * `PdfZoomControls` has its own tests; these cover what `PdfDocumentView`
 * wires around it — the hover reveal, the pointer leave, and the click-to-focus
 * that makes the scroll region keyboard-reachable. The mutation run reported
 * every site in those handlers as uncovered.
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
            height: 800 * scale,
          }),
          render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
          getTextContent: async () => ({ items: [] }),
        }),
      }),
    }),
    TextLayer: class {
      render() {
        return Promise.resolve();
      }
      cancel() {}
    },
  }),
}));

async function openReader(overrides: Partial<PdfDocumentViewProps> = {}) {
  const props: PdfDocumentViewProps = {
    materialId: "pointer-pdf",
    unitCount: 4,
    annotations: [],
    jump: null,
    onSelection: vi.fn(),
    onVisibleLocatorChange: vi.fn(),
    ...overrides,
  };
  const view = render(<PdfDocumentView {...props} />);
  const root = view.container.querySelector<HTMLElement>(".dt-reader-scroll")!;
  await waitFor(() => expect(root).toBeTruthy());
  return { ...view, root, props };
}

/**
 * The bar is a lazy chunk (`dynamic(..., { ssr: false })`), so it appears a
 * frame after the page does — a synchronous query finds nothing and the test
 * passes vacuously.
 */
async function controlsBar(view: ReturnType<typeof render>) {
  return view.findByRole("button", { name: "Zoom level" });
}

describe("the reading surface", () => {
  it("takes focus on a pointer press, so the keyboard can scroll it", async () => {
    const { root } = await openReader();
    expect(root.getAttribute("tabindex")).toBe("-1");
    act(() => {
      fireEvent.pointerDown(root);
    });
    // Without this a keyboard user cannot scroll the page or reach the shortcuts.
    expect(document.activeElement).toBe(root);
  });

  it("reveals the zoom bar when the pointer nears the bottom edge", async () => {
    const { root, ...view } = await openReader();
    const trigger = await controlsBar(view);
    // The bar's wrapper carries the opacity that `visible` drives.
    const wrapper = trigger.parentElement!.parentElement!;
    act(() => {
      fireEvent.pointerMove(root, { clientY: 0 });
    });
    await waitFor(() => expect(wrapper.className).toContain("opacity-100"));
  });

  it("hides the bar again after the pointer leaves", async () => {
    const { root, ...view } = await openReader();
    const trigger = await controlsBar(view);
    const wrapper = trigger.parentElement!.parentElement!;
    act(() => {
      fireEvent.pointerMove(root, { clientY: 0 });
    });
    await waitFor(() => expect(wrapper.className).toContain("opacity-100"));
    act(() => {
      fireEvent.pointerLeave(root);
    });
    await waitFor(() => expect(wrapper.className).not.toContain("opacity-100"), {
      timeout: 1000,
    });
  });

  it("survives a pointer move without a usable coordinate", async () => {
    const { root } = await openReader();
    act(() => {
      fireEvent.pointerMove(root, { clientY: -10 });
    });
    // The handler reads a rect and a coordinate that a synthetic event may
    // withhold; it must not throw.
    expect(root).toBeTruthy();
  });
});
