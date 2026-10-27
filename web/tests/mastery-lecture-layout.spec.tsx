import React from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMasteryLectureLayout } from "@/components/space/learning/useMasteryLectureLayout";

let frame = 1400;
let observers: { resize: () => void; disconnect: ReturnType<typeof vi.fn> }[] = [];

function Harness({ enabled = true }: { enabled?: boolean }) {
  const { gridAttach, ...panels } = useMasteryLectureLayout({ enabled });
  return (
    <div ref={gridAttach} style={panels.gridStyle} data-testid="grid">
      <output data-testid="split">{String(panels.split)}</output>
      <output data-testid="width">{String(panels.lectureWidth)}</output>
      <output data-testid="max">{String(panels.lectureMax)}</output>
    </div>
  );
}

beforeEach(() => {
  frame = 1400;
  observers = [];
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => frame);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect = vi.fn();
      constructor(resize: () => void) {
        observers.push({ resize, disconnect: this.disconnect });
      }
      observe() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function measure() {
  act(() => observers.at(-1)?.resize());
}

describe("mastery lecture layout", () => {
  it("splits into two panes once the frame is wide enough", () => {
    render(<Harness />);
    measure();
    expect(screen.getByTestId("split")).toHaveTextContent("true");
    expect(screen.getByTestId("grid").style.gridTemplateColumns).toContain("minmax(0,1fr)");
  });

  it("stays one column below the split threshold", () => {
    frame = 720;
    render(<Harness />);
    measure();
    expect(screen.getByTestId("split")).toHaveTextContent("false");
    expect(screen.getByTestId("grid").style.gridTemplateColumns).toBe("");
  });

  it("never lets the lecture squeeze the conversation past its minimum", () => {
    frame = 1000;
    render(<Harness />);
    measure();
    // 1000 - 360 chat minimum - 5 handle
    expect(screen.getByTestId("max")).toHaveTextContent("635");
  });

  it("does not split when the layout is disabled", () => {
    render(<Harness enabled={false} />);
    measure();
    expect(screen.getByTestId("split")).toHaveTextContent("false");
  });
});
