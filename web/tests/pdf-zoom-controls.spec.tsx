import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfZoomControls } from "@/components/reading/PdfZoomControls";
import type { PdfZoomPreference } from "@/lib/reading-zoom";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function controls(overrides: Partial<Parameters<typeof PdfZoomControls>[0]> = {}) {
  const props = {
    preference: { mode: "fit" } as PdfZoomPreference,
    effectivePercent: 100,
    visible: true,
    canZoomIn: true,
    canZoomOut: true,
    percentFor: (scale: number) => Math.round(scale * 100),
    onZoomIn: vi.fn(),
    onZoomOut: vi.fn(),
    onSelect: vi.fn(),
    onReset: vi.fn(),
    onActiveChange: vi.fn(),
    ...overrides,
  };
  const view = render(<PdfZoomControls {...props} />);
  return { ...view, props };
}

/**
 * The level menu's lifecycle.
 *
 * The zoom behaviour itself is covered in `pdf-reading-zoom.spec.tsx`; what
 * the CRAP report showed unreached is the menu: opening it, closing it on an
 * outside press, on Escape, and on picking a level.
 */
describe("zoom level menu", () => {
  it("stays closed until the trigger is pressed", () => {
    const view = controls();
    expect(view.queryByRole("menu")).toBeNull();
  });

  it("opens on the trigger", async () => {
    const view = controls();
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    expect(view.getByRole("menu")).toBeTruthy();
  });

  it("closes when a level is picked, and reports the choice", async () => {
    const onSelect = vi.fn();
    const view = controls({ onSelect });
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    const fit = view.getByRole("menuitemradio", { name: "Fit" });
    await act(async () => {
      fireEvent.click(fit);
    });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(view.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape", async () => {
    const view = controls();
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    await act(async () => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(view.queryByRole("menu")).toBeNull();
  });

  it("closes when the pointer lands outside it", async () => {
    const view = controls();
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    await act(async () => {
      fireEvent.pointerDown(document.body);
    });
    expect(view.queryByRole("menu")).toBeNull();
  });

  it("does not close when the pointer lands inside it", async () => {
    const view = controls();
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    const menu = view.getByRole("menu");
    await act(async () => {
      fireEvent.pointerDown(menu);
    });
    // A press on a row is not an outside press, or the click would never land.
    expect(view.getByRole("menu")).toBeTruthy();
  });

  it("reports pointer presence so hovering the bar does not hide it", async () => {
    const onActiveChange = vi.fn();
    const view = controls({ onActiveChange });
    const toolbar = view.getByRole("toolbar");
    await act(async () => {
      fireEvent.pointerEnter(toolbar);
    });
    expect(onActiveChange).toHaveBeenCalledWith(true);
    await act(async () => {
      fireEvent.pointerLeave(toolbar);
    });
    expect(onActiveChange).toHaveBeenCalledWith(false);
  });

  it("keeps the full-width wrapper transparent to pointers", () => {
    const view = controls();
    const wrapper = view.container.firstElementChild as HTMLElement;
    const toolbar = view.getByRole("toolbar");
    // jsdom does no hit-testing, so this asserts the contract the browser
    // applies: the wrapper spans the whole pane and must let wheel, click and
    // selection events through to the page beneath it, while the toolbar
    // itself stays interactive.
    expect(wrapper.className).toContain("pointer-events-none");
    expect(wrapper.className).not.toContain("pointer-events-auto");
    expect(toolbar.className).toContain("pointer-events-auto");
  });

  it("does not claim pointer presence from the wrapper's empty area", async () => {
    const onActiveChange = vi.fn();
    const view = controls({ onActiveChange });
    // The wrapper covers the pane's bottom band; entering its empty part is
    // not entering the bar, and must not keep the bar alive.
    await act(async () => {
      fireEvent.pointerEnter(view.container.firstElementChild!);
    });
    expect(onActiveChange).not.toHaveBeenCalled();
  });

  it("labels a row with what it lands at, not what it asks for", async () => {
    // `MIN_PAGE_WIDTH` (240px) is above a Letter page's 25% (204px), so picking
    // "25%" drew 29% while the toolbar said 29% and the row still claimed 25%.
    // The row prints the landed value now, so the two cannot disagree.
    const view = controls({
      percentFor: (scale: number) => (scale === 0.25 ? 29 : Math.round(scale * 100)),
    });
    await act(async () => {
      fireEvent.click(view.getByRole("button", { name: "Zoom level" }));
    });
    expect(view.getByRole("menuitemradio", { name: "29%" })).toBeTruthy();
    expect(view.queryByRole("menuitemradio", { name: "25%" })).toBeNull();
  });

  it("announces the percentage so a step has feedback without sight of the page", () => {
    const view = controls({
      preference: { mode: "fixed", scale: 1.75 },
      effectivePercent: 175,
    });
    const trigger = view.getByRole("button", { name: "Zoom level" });
    expect(trigger.getAttribute("aria-live")).toBe("polite");
    expect(trigger.textContent).toBe("175%");
  });

  it("disables the ends of the range instead of wrapping", () => {
    const view = controls({
      preference: { mode: "fixed", scale: 0.25 },
      effectivePercent: 25,
      canZoomOut: false,
    });
    expect(
      view.getByRole("button", { name: "Zoom out" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(
      view.getByRole("button", { name: "Zoom in" }).hasAttribute("disabled"),
    ).toBe(false);
  });

  it("disables zoom-in when the parent reports no further step", () => {
    const view = controls({
      preference: { mode: "fixed", scale: 4 },
      effectivePercent: 400,
      canZoomIn: false,
    });
    expect(
      view.getByRole("button", { name: "Zoom in" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("keeps zoom-in live when the budget already flattened the request", () => {
    // 3x requested but only 211% landed: the parent knows a press still does
    // something, so the button must stay enabled even though scale < MAX.
    const view = controls({
      preference: { mode: "fixed", scale: 3 },
      effectivePercent: 211,
      canZoomIn: true,
    });
    expect(
      view.getByRole("button", { name: "Zoom in" }).hasAttribute("disabled"),
    ).toBe(false);
  });
});
