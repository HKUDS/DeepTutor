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
    await waitFor(() => expect(wrapper.className).not.toMatch(/(^|\s)opacity-100($|\s)/), {
      timeout: 1000,
    });
  });

  it("keeps the bar up while the pointer is over it, even away from the edge", async () => {
    const { root, ...view } = await openReader();
    const trigger = await controlsBar(view);
    const wrapper = trigger.parentElement!.parentElement!;
    // The bar itself (the toolbar inside the transparent band) pins it:
    // without this a reader who moved the pointer onto the controls would
    // find them fading out from under them.
    const bar = trigger.parentElement!;
    act(() => {
      fireEvent.pointerEnter(bar);
    });
    await waitFor(() => expect(wrapper.className).toContain("opacity-100"));
    // Then move the pointer to the top of the pane. `pointerNearBottom` is
    // false here, so only `overControls` can keep the hide timer unarmed.
    act(() => {
      fireEvent.pointerMove(root, { clientY: -200 });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(wrapper.className).toContain("opacity-100");
  });

  it("hides the bar once the pointer leaves it", async () => {
    const { root, ...view } = await openReader();
    const trigger = await controlsBar(view);
    const wrapper = trigger.parentElement!.parentElement!;
    const bar = trigger.parentElement!;
    act(() => {
      fireEvent.pointerEnter(bar);
    });
    await waitFor(() => expect(wrapper.className).toContain("opacity-100"));
    act(() => {
      fireEvent.pointerMove(root, { clientY: -200 });
    });
    act(() => {
      fireEvent.pointerLeave(bar);
    });
    // Leaving the bar un-pins it, so the hide the move armed can now land.
    await waitFor(() => expect(wrapper.className).not.toMatch(/(^|\s)opacity-100($|\s)/), {
      timeout: 1500,
    });
  });

  it("reveals the bar only inside the bottom strip, not anywhere near it", async () => {
    const { root, ...view } = await openReader();
    const trigger = await controlsBar(view);
    const wrapper = trigger.parentElement!.parentElement!;
    // jsdom has no layout, so the handler's own rect is stubbed: a 500px tall
    // root whose bottom edge is at 580 leaves the reveal strip starting at 508.
    // A pointer 100px above that edge is well outside it.
    root.getBoundingClientRect = () =>
      new DOMRect(120, 80, 600, 500);
    act(() => {
      fireEvent.pointerMove(root, { clientY: 480 });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(wrapper.className).not.toMatch(/(^|\s)opacity-100($|\s)/);
    act(() => {
      fireEvent.pointerMove(root, { clientY: 540 });
    });
    // 40px above the bottom edge: inside the strip, so the bar comes up.
    await waitFor(() => expect(wrapper.className).toContain("opacity-100"));
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
