import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const device = vi.hoisted(() => ({ isMobile: false }));

vi.mock("@/hooks/useDevice", () => ({
  useDevice: () => ({
    device: device.isMobile ? "mobile" : "tablet",
    isMobile: device.isMobile,
    isTablet: !device.isMobile,
    isDesktop: false,
    isCompact: true,
  }),
}));

const { AnnotationPopover } = await import(
  "@/components/reading/AnnotationPopover"
);

const noop = () => undefined;

function renderPopover(overrides: Partial<Parameters<typeof AnnotationPopover>[0]> = {}) {
  const onDismiss = vi.fn();
  const props = {
    anchor: { x: 120, y: 200 },
    quote: "the slope of the line",
    onHighlight: noop,
    onUnderline: noop,
    onNote: noop,
    onCitation: noop,
    onAsk: noop,
    onDismiss,
    ...overrides,
  };
  const view = render(<AnnotationPopover {...props} />);
  return { onDismiss, ...view };
}

/** Five AI actions: three chips inline, two behind the ⋯ overflow. */
const aiActions = [1, 2, 3, 4, 5].map((n) => ({
  key: `a${n}`,
  label: `Action ${n}`,
  title: `Action ${n} in full`,
  onClick: noop,
}));

/**
 * #916, dictionary half: on a phone the selection panel — the panel a
 * long-press on a word summons, carrying explain and translate — is a
 * bottom card rather than an anchored popover. Short content sits at its
 * collapsed height; the expanded states cap and scroll; the handle closes
 * on a pull-down. Desktop keeps the anchored popover unchanged.
 */
describe("selection panel as a bottom card below 768px", () => {
  beforeEach(() => {
    device.isMobile = true;
  });

  it("docks to the bottom edge with safe-area padding and a collapsed body", () => {
    const { container } = renderPopover({ aiActions });

    const sheet = screen.getByRole("dialog", { name: "Annotate selection" });
    expect(sheet.className).toContain("dt-reader-sheet");
    expect(sheet.className).toContain("bottom-0");
    expect(sheet.className).toContain("inset-x-0");
    // The home-indicator strip stays clear of the card's buttons.
    expect(sheet.className).toContain("pb-[calc(env(safe-area-inset-bottom)+10px)]");
    expect(container.querySelector('[data-scroll="short"]')).not.toBeNull();
    const body = container.querySelector('[data-scroll="short"]') as HTMLElement;
    // Short content collapses: nothing to scroll, no forced height.
    expect(body.className).not.toContain("overflow-y-auto");
    expect(body.className).not.toContain("max-h-");
    expect(screen.getByTestId("sheet-handle")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ask about this" }),
    ).toBeVisible();
  });

  it("switches the body to capped and scrollable for long content", async () => {
    const user = userEvent.setup();
    const { container } = renderPopover({ aiActions });

    // Long content #1: the overflow list of extra AI actions.
    await user.click(screen.getByRole("button", { name: "More actions" }));
    let body = container.querySelector('[data-scroll]') as HTMLElement;
    expect(body.getAttribute("data-scroll")).toBe("long");
    expect(body.className).toContain("max-h-[60dvh]");
    expect(body.className).toContain("overflow-y-auto");
    expect(body.className).toContain("overscroll-contain");
    expect(within(body).getByRole("button", { name: "Action 4 in full" })).toBeVisible();

    // Long content #2: the note editor.
    await user.click(screen.getByRole("button", { name: "Add note" }));
    body = container.querySelector('[data-scroll]') as HTMLElement;
    expect(body.getAttribute("data-scroll")).toBe("long");
    expect(screen.getByPlaceholderText("Your note…")).toBeVisible();
  });

  it("closes on a pull-down of the handle, not on a nudge", () => {
    const { onDismiss } = renderPopover({ aiActions });
    const handle = screen.getByTestId("sheet-handle");

    // A nudge moves the card but keeps it open.
    fireEvent.pointerDown(handle, { pointerId: 3, clientY: 300 });
    fireEvent.pointerMove(handle, { pointerId: 3, clientY: 316 });
    fireEvent.pointerUp(handle, { pointerId: 3, clientY: 318 });
    expect(onDismiss).not.toHaveBeenCalled();

    // A pull past the threshold dismisses.
    fireEvent.pointerDown(handle, { pointerId: 4, clientY: 300 });
    fireEvent.pointerMove(handle, { pointerId: 4, clientY: 331 });
    fireEvent.pointerUp(handle, { pointerId: 4, clientY: 355 });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("still closes on Escape and on a tap outside", () => {
    const { onDismiss } = renderPopover({ aiActions });

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);

    fireEvent.pointerDown(document.body);
    expect(onDismiss).toHaveBeenCalledTimes(2);
  });
});

describe("selection panel above 768px (desktop regression)", () => {
  beforeEach(() => {
    device.isMobile = false;
  });

  it("stays the anchored popover, not a bottom card", () => {
    const { container } = renderPopover({ aiActions });

    const popover = screen.getByRole("dialog", { name: "Annotate selection" });
    expect(popover.className).toContain("dt-reader-popover");
    expect(popover.className).not.toContain("dt-reader-sheet");
    expect(popover.className).not.toContain("bottom-0");
    // No sheet furniture on the desktop frame: no handle, no scroll region.
    expect(container.querySelector('[data-scroll]')).toBeNull();
    expect(container.querySelector('[data-testid="sheet-handle"]')).toBeNull();
    expect(screen.getByRole("button", { name: "Ask about this" })).toBeVisible();
  });
});
