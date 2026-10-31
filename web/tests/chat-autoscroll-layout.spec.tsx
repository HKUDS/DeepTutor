import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  isScrollbarPointer,
  resolveFollowDecision,
  useChatAutoScroll,
} from "@/hooks/useChatAutoScroll";
import { useLayoutEffect } from "react";

let height: number;
let top: number;
let following: { current: boolean };
let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;
let mutations: Array<() => void>;
let resizes: Array<() => void>;

function flushLayout() {
  act(() => {
    mutations.forEach(callback => callback());
    resizes.forEach(callback => callback());
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach(callback => callback(performance.now()));
  });
}

function Harness({ streaming = true }: { streaming?: boolean }) {
  const { containerRef, endRef, handleScroll, shouldAutoScrollRef, isFollowing } = useChatAutoScroll({ hasMessages: true, isStreaming: streaming,
    composerHeight: 0, messageCount: 2, lastMessageContent: "Reply" });
  useLayoutEffect(() => { following = shouldAutoScrollRef; }, [shouldAutoScrollRef]);
  return <>
    <div data-testid="scroll" onScroll={handleScroll} ref={containerRef}>
      <div><p>Question</p><p>Reply</p><button>Open working notes</button><div ref={endRef} /></div>
    </div>
    <span data-testid="following-state">{isFollowing ? "yes" : "no"}</span>
  </>;
}

beforeEach(() => {
  height = 1000; top = 0; nextFrame = 0;
  frames = new Map(); mutations = []; resizes = [];
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(200);
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(200);
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(() => height);
  vi.spyOn(Element.prototype, "scrollTop", "get").mockImplementation(() => top);
  vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation(value => {
    top = Math.max(0, Math.min(value, height - 200));
  });
  vi.useFakeTimers();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback); return nextFrame;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("MutationObserver", class {
    callback: () => void;
    constructor(callback: () => void) { this.callback = callback; }
    observe() { mutations.push(this.callback); }
    disconnect() { mutations = mutations.filter(callback => callback !== this.callback); }
  });
  vi.stubGlobal("ResizeObserver", class {
    callback: () => void;
    constructor(callback: () => void) { this.callback = callback; }
    observe() { resizes.push(this.callback); }
    unobserve() {}
    disconnect() { resizes = resizes.filter(callback => callback !== this.callback); }
  });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("does not mistake automatic scroll clamping on a collapsing trace for user scrolling", () => {
  render(<Harness />); flushLayout();
  expect(top).toBe(800);
  // The browser clamps scrollTop when a disclosure makes the document shorter.
  height = 500; top = 300;
  fireEvent.scroll(screen.getByTestId("scroll")); flushLayout();
  expect(following.current).toBe(true);
  height = 1400; flushLayout();
  expect(top).toBe(1200);
});

it("keeps the latest messages in view when late content grows after stream settlement", () => {
  render(<Harness streaming={false} />); flushLayout();
  act(() => vi.advanceTimersByTime(15000));
  height = 1800; flushLayout();
  expect(top).toBe(1600);
});

it("does not pull a reader back down after an upward wheel gesture", () => {
  render(<Harness />); flushLayout();
  fireEvent.wheel(screen.getByTestId("scroll"), { deltaY: -20 });
  top = 400; fireEvent.scroll(screen.getByTestId("scroll"));
  height = 1800; flushLayout();
  expect(top).toBe(400);
  expect(following.current).toBe(false);
});

it("recognizes manual scrollbar movement without requiring a wheel gesture", () => {
  render(<Harness />); flushLayout();
  top = 400; fireEvent.scroll(screen.getByTestId("scroll"));
  height = 1800; flushLayout();
  expect(top).toBe(400);
  expect(following.current).toBe(false);
});

it("releases follow on a small upward scrollbar drag near the live end", () => {
  render(<Harness />); flushLayout();
  // A 20 px drag is inside the old 80 px "near bottom" band and emits no
  // wheel/key event, so only the scroll position can identify it.
  top = 780; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(false);
  height = 1800; flushLayout();
  expect(top).toBe(780);
});

it("does not re-arm follow when a collapse clamps a detached reader to the bottom", () => {
  render(<Harness />); flushLayout();
  top = 400; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(false);
  // The trace collapses and the browser clamps scrollTop to the new maximum.
  height = 400; top = 200;
  fireEvent.scroll(screen.getByTestId("scroll")); flushLayout();
  expect(following.current).toBe(false);
  expect(top).toBe(200);
});

it("resumes following only when the reader returns to the live end", () => {
  render(<Harness />); flushLayout();
  top = 400; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(false);
  // Still detached 50 px from the bottom: no accidental re-arm.
  top = 750; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(false);
  // Reaching the live end resumes the pin.
  top = 800; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(true);
  height = 1200; flushLayout();
  expect(top).toBe(1000);
});

it("respects even a small deliberate upward scroll near the live end", () => {
  render(<Harness />); flushLayout();
  fireEvent.wheel(screen.getByTestId("scroll"), { deltaY: -20 });
  top = 780; fireEvent.scroll(screen.getByTestId("scroll"));
  height = 1800; flushLayout();
  expect(top).toBe(780);
  expect(following.current).toBe(false);
  top = 1600; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(following.current).toBe(true);
});

it("does not yank the viewport when the reader opens working notes", () => {
  render(<Harness streaming={false} />); flushLayout();
  fireEvent.pointerDown(screen.getByRole("button", { name: "Open working notes" }));
  height = 1800; flushLayout();
  expect(top).toBe(800);
  expect(following.current).toBe(false);
});

it("lets the reader drag the scrollbar up while the reply is still growing (#2072)", () => {
  render(<Harness />); flushLayout();
  expect(top).toBe(800);
  // A scrollbar drag fires no wheel/key event, and while streaming the reply
  // grows between the drag and its scroll event.
  top = 300; height = 1100;
  fireEvent.scroll(screen.getByTestId("scroll")); flushLayout();
  expect(following.current).toBe(false);
  height = 1400; flushLayout();
  expect(top).toBe(300);
  // Dragging back to the live end follows again, even as it grows.
  top = 1220; height = 1420;
  fireEvent.scroll(screen.getByTestId("scroll")); flushLayout();
  expect(following.current).toBe(true);
  height = 1600; flushLayout();
  expect(top).toBe(1400);
});

it("publishes detached state so the caller can offer back-to-latest", () => {
  render(<Harness />); flushLayout();
  expect(screen.getByTestId("following-state")).toHaveTextContent("yes");
  top = 400; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(screen.getByTestId("following-state")).toHaveTextContent("no");
  top = 800; fireEvent.scroll(screen.getByTestId("scroll"));
  expect(screen.getByTestId("following-state")).toHaveTextContent("yes");
});

it("releases follow on a scrollbar press before the next streamed frame", () => {
  render(<Harness />); flushLayout();
  const scroll = screen.getByTestId("scroll");
  vi.spyOn(scroll, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, right: 215, bottom: 200,
    width: 215, height: 200, x: 0, y: 0, toJSON: () => ({}),
  } as DOMRect);
  // Press in the vertical scrollbar gutter (content is 200 px wide).
  fireEvent.pointerDown(scroll, { clientX: 210, clientY: 100 });
  expect(following.current).toBe(false);
  // The reply grows before the drag's first scroll event arrives.
  height = 1800; flushLayout();
  expect(top).toBe(800);
  // The drag itself stays put while the reply keeps growing.
  top = 700; height = 1900;
  fireEvent.scroll(scroll); flushLayout();
  expect(following.current).toBe(false);
  expect(top).toBe(700);
  height = 2200; flushLayout();
  expect(top).toBe(700);
});

it("classifies scroll intent without treating a shrink clamp as a rejoin", () => {
  expect(resolveFollowDecision({
    scrollTop: 780, previousTop: 800, previousHeight: 1000,
    height: 1000, viewport: 200, following: true,
  })).toBe("detach");
  expect(resolveFollowDecision({
    scrollTop: 200, previousTop: 400, previousHeight: 1000,
    height: 400, viewport: 200, following: false,
  })).toBe("hold");
  expect(resolveFollowDecision({
    scrollTop: 800, previousTop: 300, previousHeight: 1000,
    height: 1000, viewport: 200, following: false,
  })).toBe("follow");
});

it("recognizes scrollbar geometry separately from content", () => {
  const container = { clientWidth: 200, clientHeight: 200, clientLeft: 0, clientTop: 0 };
  const rect = { left: 0, top: 0, width: 215, height: 200 };
  expect(isScrollbarPointer(container, {
    offsetX: 210, offsetY: 50, clientX: 210, clientY: 50,
  }, rect)).toBe(true);
  expect(isScrollbarPointer(container, {
    offsetX: 100, offsetY: 50, clientX: 100, clientY: 50,
  }, rect)).toBe(false);
});
