import React, { useRef } from "react";
import { act, render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useTranscriptFollow } from "@/components/watching/useTranscriptFollow";

let resize: () => void;
let frame: FrameRequestCallback;
const scroll = vi.fn();
let reduced = false;
let desktop = false;
let captionTop = 520;
function Harness({ start = 10, enabled = true }) {
  const ref = useRef<HTMLDivElement>(null);
  useTranscriptFollow(ref, start, enabled);
  return <div data-watching-workspace="true"><div className="watching-live-captions" /><div ref={ref} data-testid="rail"><div className="watching-transcript-tools" /><div data-cue-start="10" /><div data-cue-start="20" /></div></div>;
}
beforeEach(() => {
  reduced = false;
  desktop = false;
  captionTop = 520;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { frame = cb; return 1; });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.stubGlobal("ResizeObserver", class { constructor(cb: () => void) { resize = cb; } observe() {} disconnect() {} });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("900px") ? desktop : reduced }));
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: scroll });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.classList.contains("watching-live-captions")) return {top: captionTop, height: 60} as DOMRect;
    const rail = this.hasAttribute("data-testid");
    const toolbar = this.classList.contains("watching-transcript-tools");
    return { top: rail ? 100 : toolbar ? 100 : 700, height: rail ? 600 : toolbar ? 100 : 40 } as DOMRect;
  });
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(2000);
});
it("centers the current sentence below the sticky controls, not the full page", () => {
  render(<Harness />);
  act(() => frame(0));
  expect(scroll).toHaveBeenLastCalledWith({ top: 270, behavior: "smooth" });
});
it("does not scroll on time updates within the same cue; recenters on resize and cue changes", () => {
  const view = render(<Harness />);
  act(() => frame(0));
  scroll.mockClear();
  view.rerender(<Harness />);
  expect(scroll).not.toHaveBeenCalled();
  act(() => { resize(); frame(0); });
  expect(scroll).toHaveBeenLastCalledWith({ top: 270, behavior: "smooth" });
  view.rerender(<Harness start={20} />);
  act(() => frame(0));
  expect(scroll).toHaveBeenLastCalledWith({ top: 270, behavior: "smooth" });
});
it("stops following during manual browsing/search and resumes without animation for reduced motion", () => {
  const view = render(<Harness />);
  act(() => frame(0));
  view.rerender(<Harness enabled={false} />);
  expect(scroll).toHaveBeenLastCalledWith({ top: 0, behavior: "instant" });
  scroll.mockClear();
  view.rerender(<Harness enabled={false} start={20} />);
  expect(scroll).not.toHaveBeenCalled();
  reduced = true;
  view.rerender(<Harness start={20} />);
  act(() => frame(0));
  expect(scroll).toHaveBeenLastCalledWith({ top: 270, behavior: "instant" });
});

it("aligns desktop transcription with the video caption area", () => {
  desktop = true;
  render(<Harness />);
  act(() => frame(0));
  expect(scroll).toHaveBeenLastCalledWith({ top: 170, behavior: "smooth" });
});
it("keeps context above and below when the desktop video caption anchor is near an edge", () => {
  desktop = true;
  captionTop = 900;
  render(<Harness />);
  act(() => frame(0));
  expect(scroll).toHaveBeenLastCalledWith({ top: 145, behavior: "smooth" });
});
