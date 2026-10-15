import { useRef } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";

let notifyResize: ResizeObserverCallback;
const disconnect = vi.fn();
let contentHeight = 26;

function Input({ value = "", min = 28 }: { value?: string; min?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoSizedTextarea(ref, value, { min, max: 200 });
  return <textarea ref={ref} value={value} readOnly rows={1} placeholder="Ask about this material…" />;
}

function resize(width: number) {
  act(() => notifyResize(
    [{ contentRect: { width } } as ResizeObserverEntry],
    {} as ResizeObserver,
  ));
}

beforeEach(() => {
  contentHeight = 26;
  disconnect.mockClear();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: ResizeObserverCallback) { notifyResize = callback; }
    observe() {}
    disconnect = disconnect;
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
    const field = this as HTMLTextAreaElement;
    // Browsers include a wrapping placeholder even when the value is empty.
    return !field.value && field.placeholder ? 520 : contentHeight;
  });
});

afterEach(() => vi.unstubAllGlobals());

it("keeps an empty field compact without losing its placeholder", () => {
  const { rerender } = render(<Input />);
  const input = screen.getByRole("textbox");
  expect(input).toHaveStyle({ height: "28px", overflowY: "hidden" });
  expect(input).toHaveAttribute("placeholder", "Ask about this material…");
  rerender(<Input min={64} />);
  expect(input).toHaveStyle({ height: "64px" });
});

it("caps long input and shrinks again after sending or deleting it", () => {
  contentHeight = 520;
  const { rerender } = render(<Input value={"line\n".repeat(20)} />);
  const input = screen.getByRole("textbox");
  expect(input).toHaveStyle({ height: "200px", overflowY: "auto" });
  contentHeight = 26;
  rerender(<Input />);
  expect(input).toHaveStyle({ height: "28px", overflowY: "hidden" });
});

it("remeasures wrapping when a sidebar changes width, but ignores height-only notifications", () => {
  contentHeight = 156;
  const { unmount } = render(<Input value="A question that wraps in a narrow sidebar" />);
  const input = screen.getByRole("textbox");
  resize(150);
  expect(input).toHaveStyle({ height: "156px" });
  contentHeight = 52;
  resize(400);
  expect(input).toHaveStyle({ height: "52px" });
  const measured = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get");
  measured.mockClear();
  resize(400);
  expect(measured).not.toHaveBeenCalled();
  unmount();
  expect(disconnect).toHaveBeenCalledOnce();
});

it("remeasures after a hidden panel reopens at the same width", () => {
  const { rerender } = render(<Input value="Question" />);
  resize(400);
  resize(0);
  contentHeight = 0;
  rerender(<Input value={"Question\n".repeat(8)} />);
  contentHeight = 208;
  resize(400);
  expect(screen.getByRole("textbox")).toHaveStyle({ height: "200px", overflowY: "auto" });
});
