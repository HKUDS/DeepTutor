import { StrictMode, useRef } from "react";
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

it("reuses one out-of-flow measurement node across edits and removes it on unmount", () => {
  const append = vi.spyOn(document.body, "appendChild");
  const { rerender, unmount } = render(<Input value="first" />);
  const mirror = document.querySelector('textarea[aria-hidden="true"]');
  for (let index = 0; index < 45; index += 1) {
    rerender(<Input value={`edit ${index}`} />);
  }
  expect(append.mock.calls.filter(([node]) => node instanceof HTMLTextAreaElement)).toHaveLength(1);
  expect(mirror).not.toBeNull();
  expect(document.querySelector('textarea[aria-hidden="true"]')).toBe(mirror);
  unmount();
  expect(mirror?.isConnected).toBe(false);
  expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull();
});

it("keeps separate measurement nodes for simultaneous composers", () => {
  const { rerender, unmount } = render(<><Input value="left" /><Input value="right" /></>);
  const mirrors = [...document.querySelectorAll('textarea[aria-hidden="true"]')];
  expect(mirrors).toHaveLength(2);
  expect(mirrors.map(node => (node as HTMLTextAreaElement).value)).toEqual(["left", "right"]);
  rerender(<><Input value="left edited" /><Input value="right" /></>);
  expect([...document.querySelectorAll('textarea[aria-hidden="true"]')]).toEqual(mirrors);
  expect((mirrors[0] as HTMLTextAreaElement).value).toBe("left edited");
  unmount();
  expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull();
});

it("cleans up the Strict Mode trial mount without losing the active mirror", () => {
  const { rerender, unmount } = render(<StrictMode><Input value="first" /></StrictMode>);
  expect(document.querySelectorAll('textarea[aria-hidden="true"]')).toHaveLength(1);
  rerender(<StrictMode><Input value="edited" /></StrictMode>);
  expect(document.querySelectorAll('textarea[aria-hidden="true"]')).toHaveLength(1);
  unmount();
  expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull();
});
