import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Tooltip, { placeTooltip } from "@/shared/ui/Tooltip";

afterEach(() => {
  vi.useRealTimers();
});

function visualTooltip(): HTMLElement | null {
  return document.body.querySelector('[role="tooltip"].fixed');
}

it("keeps an accessible description connected before the visual hint opens", () => {
  render(
    <Tooltip label="Open settings">
      <button type="button">Settings</button>
    </Tooltip>,
  );
  const button = screen.getByRole("button", { name: "Settings" });
  const describedBy = button.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  expect(document.getElementById(describedBy!)).toHaveTextContent("Open settings");
});

it("renders through a body portal and keeps keyboard focus visible", async () => {
  const { container } = render(
    <div className="overflow-hidden">
      <Tooltip label="A long keyboard hint" side="top">
        <button type="button">Action</button>
      </Tooltip>
    </div>,
  );
  const button = screen.getByRole("button", { name: "Action" });
  fireEvent.focus(button);
  await waitFor(() =>
    expect(visualTooltip()?.parentElement).toBe(document.body),
  );

  fireEvent.pointerLeave(button.parentElement!, { pointerType: "mouse" });
  expect(visualTooltip()).toBeInTheDocument();
  expect(container.querySelector('[role="tooltip"].fixed')).toBeNull();

  fireEvent.keyDown(button.parentElement!, { key: "Escape" });
  expect(visualTooltip()).toBeNull();
});

it("shows on touch and on hover over a disabled trigger", async () => {
  vi.useFakeTimers();
  render(
    <Tooltip label="Unavailable because setup is incomplete" delay={20}>
      <button type="button" disabled>
        Disabled
      </button>
    </Tooltip>,
  );
  const wrapper = screen.getByRole("button", { name: "Disabled" }).parentElement!;
  fireEvent.pointerEnter(wrapper, { pointerType: "mouse" });
  await act(async () => {
    vi.advanceTimersByTime(20);
    await import("@/shared/ui/TooltipLayer");
  });
  expect(visualTooltip()).toHaveTextContent("Unavailable because setup is incomplete");

  fireEvent.pointerLeave(wrapper, { pointerType: "mouse" });
  expect(visualTooltip()).toBeNull();
  fireEvent.pointerDown(wrapper, { pointerType: "touch" });
  expect(visualTooltip()).toHaveTextContent("Unavailable because setup is incomplete");
});

it("flips and clamps near viewport edges", () => {
  const rect = (values: Partial<DOMRect>): DOMRect =>
    ({
      x: 0,
      y: 0,
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      width: 0,
      height: 0,
      toJSON: () => ({}),
      ...values,
    }) as DOMRect;
  const placed = placeTooltip(
    rect({ left: 4, right: 24, top: 40, bottom: 60, width: 20, height: 20 }),
    rect({ width: 180, height: 40 }),
    "left",
    240,
    120,
  );
  expect(placed.side).toBe("right");
  expect(placed.left).toBeGreaterThanOrEqual(8);
  expect(placed.top).toBeGreaterThanOrEqual(8);
  expect(placed.left + 180).toBeLessThanOrEqual(232);
});
