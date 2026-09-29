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

it("keeps list cards as list items while exposing focus and touch hints", async () => {
  render(
    <ul>
      <Tooltip label="View details" as="li">
        <div role="button" tabIndex={0} aria-label="View details: Example">
          Example
          <button type="button">Edit</button>
        </div>
      </Tooltip>
    </ul>,
  );

  const card = screen.getByRole("button", { name: "View details: Example" });
  const list = screen.getByRole("list");
  expect(list.children).toHaveLength(1);
  expect(list.firstElementChild?.tagName).toBe("LI");
  expect(card.getAttribute("aria-describedby")).toBeTruthy();
  expect(document.getElementById(card.getAttribute("aria-describedby")!)).toHaveTextContent(
    "View details",
  );

  fireEvent.focus(card);
  await waitFor(() => expect(visualTooltip()).toHaveTextContent("View details"));
  fireEvent.pointerOver(screen.getByRole("button", { name: "Edit" }), { pointerType: "mouse" });
  expect(visualTooltip()).toBeNull();
  fireEvent.focus(card);
  await waitFor(() => expect(visualTooltip()).toHaveTextContent("View details"));
  fireEvent.blur(card);
  expect(visualTooltip()).toBeNull();

  fireEvent.pointerDown(card, { pointerType: "touch" });
  await waitFor(() => expect(visualTooltip()).toHaveTextContent("View details"));
  fireEvent.pointerDown(screen.getByRole("button", { name: "Edit" }), { pointerType: "touch" });
  expect(visualTooltip()).toBeNull();
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
