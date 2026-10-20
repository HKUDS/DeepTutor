import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
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
  const { containerRef, endRef, handleScroll, shouldAutoScrollRef } = useChatAutoScroll({ hasMessages: true, isStreaming: streaming,
    composerHeight: 0, messageCount: 2, lastMessageContent: "Reply" });
  useLayoutEffect(() => { following = shouldAutoScrollRef; }, [shouldAutoScrollRef]);
  return <div data-testid="scroll" onScroll={handleScroll} ref={containerRef}>
    <div><p>Question</p><p>Reply</p><button>Open working notes</button><div ref={endRef} /></div>
  </div>;
}

beforeEach(() => {
  height = 1000; top = 0; nextFrame = 0;
  frames = new Map(); mutations = []; resizes = [];
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(200);
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
