import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfImageZoomOverlay } from "@/components/reading/PdfImageZoomOverlay";

vi.mock("react-i18next", () => {
  // Interpolate `{{n}}` the way i18next does, so the label reads as the
  // component renders it rather than as the raw template.
  const t = (key: string, options?: Record<string, unknown>) =>
    options && "n" in options
      ? key.replace("{{n}}", String(options.n))
      : key;
  return { useTranslation: () => ({ t }) };
});

/**
 * The picture preview.
 *
 * The canvas render needs pdf.js, so the doc is a stub: what is worth
 * asserting is the shell around it — that it opens as a modal, closes three
 * ways, and reports the zoom it is at.
 */
const doc = {
  getPage: async () => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: 600 * scale,
      height: 800 * scale,
    }),
    render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
  }),
} as never;

/**
 * Mounts the preview and lets its first paint settle.
 *
 * The component paints the picture in an effect, so its state update lands on a
 * later tick. Returning before that update arrives makes it happen outside
 * `act`, which the shared setup turns into an unhandled rejection — the
 * assertions still passed, but vitest exited non-zero on the warning.
 */
async function overlay(overrides: { onClose?: () => void } = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  const view = render(
    <PdfImageZoomOverlay
      doc={doc}
      locator={3}
      box={{ x0: 0.1, y0: 0.2, x1: 0.6, y1: 0.5 }}
      onClose={onClose}
    />,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return { ...view, onClose };
}

describe("picture preview", () => {
  it("opens as a modal naming the page it came from", async () => {
    await overlay();
    const dialog = screen.getByRole("dialog", { name: "Image preview" });
    expect(dialog).toBeTruthy();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("Page 3")).toBeTruthy();
  });

  it("closes on Escape", async () => {
    const { onClose } = await overlay();
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on a click on the empty stage around the picture", async () => {
    const { onClose } = await overlay();
    const dialog = screen.getByRole("dialog", { name: "Image preview" });
    // The stage fills the space below the toolbar, so a click on the dialog
    // itself never happens in a browser — the stage swallows it. This used to
    // stop propagation for every click, which made the surrounding area dead
    // and left Escape as the only way out.
    const stage = dialog.lastElementChild as HTMLElement;
    await act(async () => {
      fireEvent.click(stage);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on a click on the picture itself", async () => {
    const { onClose } = await overlay();
    const dialog = screen.getByRole("dialog", { name: "Image preview" });
    const stage = dialog.lastElementChild as HTMLElement;
    const canvas = stage.querySelector("canvas")!;
    await act(async () => {
      fireEvent.click(canvas);
    });
    // A click on the picture is a click on the thing being looked at.
    expect(onClose).not.toHaveBeenCalled();
  });

  it("takes focus while open and gives it back on close", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const { onClose, unmount } = await overlay();
    // ⌘+/− and the arrow keys follow focus, so a modal that leaves it on the
    // page behind it hands those keys to the wrong surface.
    expect(document.activeElement).toBe(
      screen.getByRole("dialog", { name: "Image preview" }),
    );
    await act(async () => {
      unmount();
    });
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
    void onClose;
  });

  it("does not close when the click lands on the toolbar", async () => {
    const { onClose } = await overlay();
    const toolbar = screen.getByText("Page 3").closest("div")!;
    await act(async () => {
      fireEvent.click(toolbar);
    });
    // A press on a control is not a press on the backdrop.
    expect(onClose).not.toHaveBeenCalled();
  });

  it("offers zoom controls", async () => {
    await overlay();
    expect(screen.getByLabelText("Zoom in")).toBeTruthy();
    expect(screen.getByLabelText("Zoom out")).toBeTruthy();
  });

  it("ignores keys other than Escape", async () => {
    const { onClose } = await overlay();
    await act(async () => {
      fireEvent.keyDown(window, { key: "a" });
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
