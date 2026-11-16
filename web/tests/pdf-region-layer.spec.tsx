import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PdfRegionLayer } from "@/components/reading/PdfRegionLayer";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

/**
 * Marking a page area (#2741): the drag surface exists only in area mode, so
 * scrolling, text selection and picture hotspots are untouched without it.
 *
 * The layer sits on the whole-page surface; its client rect is stubbed to a
 * page drawn at 100,50 and 400x600 CSS px.
 */
const SURFACE = new DOMRect(100, 50, 400, 600);

function renderLayer(props: Partial<Parameters<typeof PdfRegionLayer>[0]> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <div className="relative">
      <PdfRegionLayer
        locator={3}
        selecting={false}
        marked={null}
        onSelect={onSelect}
        {...props}
      />
    </div>,
  );
  const layer = view.container.querySelector<HTMLElement>("[data-region-layer]");
  if (layer) vi.spyOn(layer, "getBoundingClientRect").mockReturnValue(SURFACE);
  return { ...view, layer, onSelect };
}

function drag(layer: HTMLElement, from: [number, number], to: [number, number]) {
  const pointer = { pointerId: 7, button: 0, pointerType: "touch" };
  fireEvent.pointerDown(layer, { ...pointer, clientX: from[0], clientY: from[1] });
  fireEvent.pointerMove(layer, { ...pointer, clientX: to[0], clientY: to[1] });
  fireEvent.pointerUp(layer, { ...pointer, clientX: to[0], clientY: to[1] });
}

describe("PdfRegionLayer", () => {
  it("renders nothing outside area mode when no area is marked", () => {
    const { layer } = renderLayer();
    expect(layer).toBeNull();
  });

  it("captures the drag in area mode and reports a page-normalised box", () => {
    const { layer, onSelect } = renderLayer({ selecting: true });
    expect(layer).not.toBeNull();
    // A finger draws instead of scrolling — only while the mode is on.
    expect(layer!.style.touchAction).toBe("none");

    drag(layer!, [140, 110], [300, 350]);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(3, { x0: 0.1, y0: 0.1, x1: 0.5, y1: 0.5 });
  });

  it("ignores a tap and a cancelled drag", () => {
    const { layer, onSelect } = renderLayer({ selecting: true });
    drag(layer!, [200, 200], [201, 201]);
    fireEvent.pointerDown(layer!, { pointerId: 8, button: 0, clientX: 140, clientY: 110 });
    fireEvent.pointerCancel(layer!, { pointerId: 8, clientX: 300, clientY: 350 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("ignores a secondary mouse button", () => {
    const { layer, onSelect } = renderLayer({ selecting: true });
    fireEvent.pointerDown(layer!, { pointerId: 9, button: 2, clientX: 140, clientY: 110 });
    fireEvent.pointerUp(layer!, { pointerId: 9, button: 2, clientX: 300, clientY: 350 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("draws a marked area without taking the pointer once the mode is off", () => {
    const { layer, container } = renderLayer({
      marked: { x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.4 },
      actions: <button type="button">Ask about this area</button>,
    });
    expect(layer).not.toBeNull();
    expect(layer!.className).toContain("pointer-events-none");
    expect(layer!.style.touchAction).toBe("");
    const box = container.querySelector<HTMLElement>('[data-region-box="marked"]')!;
    expect(box.style.left).toBe("10%");
    expect(box.style.top).toBe("20%");
    expect(box.style.width).toBe("40%");
    // The actions stay clickable on top of the pass-through layer.
    const ask = container.querySelector("button")!;
    expect(ask.parentElement!.className).toContain("pointer-events-auto");
  });
});
