import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityMark } from "@/components/activity/ActivityMark";
import { SessionAvatar } from "@/components/sidebar/SessionAvatar";

function canvasClock() {
  let id = 0;
  const pending = new Map<number, FrameRequestCallback>();
  const clearRect = vi.fn();
  const context = {
    setTransform: vi.fn(), clearRect, beginPath: vi.fn(), arc: vi.fn(),
    fill: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("IntersectionObserver", undefined);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    pending.set(++id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (key: number) => pending.delete(key));
  return {
    pending,
    clearRect,
    frame() {
      const callbacks = [...pending.values()];
      pending.clear();
      act(() => callbacks.forEach(callback => callback(performance.now())));
    },
  };
}

describe("settled activity mark animation", () => {
  it.each(["session", "activity"])("does not keep drawing a settled %s mark", kind => {
    const clock = canvasClock();
    const { rerender, unmount } = render(kind === "session"
      ? <SessionAvatar sessionId="session-a" mark="idle" />
      : <ActivityMark state="done" />);
    try {
      clock.clearRect.mockClear();
      clock.frame();
      expect(clock.clearRect).not.toHaveBeenCalled();
      expect(clock.pending.size).toBe(0);
      rerender(kind === "session"
        ? <SessionAvatar sessionId="session-a" mark="running" />
        : <ActivityMark state="running" />);
      clock.clearRect.mockClear();
      clock.frame();
      expect(clock.clearRect).toHaveBeenCalled();
      rerender(kind === "session"
        ? <SessionAvatar sessionId="session-a" mark="idle" />
        : <ActivityMark state="done" />);
      clock.clearRect.mockClear();
      clock.frame();
      expect(clock.clearRect).not.toHaveBeenCalled();
      expect(clock.pending.size).toBe(0);
    } finally {
      unmount();
      vi.unstubAllGlobals();
    }
  });
});
