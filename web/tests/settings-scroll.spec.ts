import { afterEach, describe, expect, it, vi } from "vitest";
import { scrollToSettingsElement, scrollToSettingsSection } from "@/features/settings/navigation/settings-scroll";

afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals(); });

function fixture() {
  const outer = document.createElement("div");
  outer.style.overflow = "hidden";
  const scroller = document.createElement("div");
  scroller.dataset.settingsScroll = "";
  const target = document.createElement("div");
  target.id = "provider-detail";
  target.style.scrollMarginTop = "16px";
  outer.append(scroller);
  scroller.append(target);
  document.body.append(outer);
  scroller.scrollTop = 200;
  Object.defineProperty(scroller, "clientTop", { value: 1 });
  vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue({ top: 40 } as DOMRect);
  vi.spyOn(target, "getBoundingClientRect").mockReturnValue({ top: 340 } as DOMRect);
  const scrollTo = vi.fn();
  scroller.scrollTo = scrollTo;
  const scrollIntoView = vi.fn();
  target.scrollIntoView = scrollIntoView;
  const rootScroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.push(callback); return frames.length; });
  return { target, scrollTo, scrollIntoView, rootScroll, frames };
}

describe("settings detail scrolling", () => {
  it("scrolls only the settings document, accounting for existing scroll, border and margin", () => {
    const { target, scrollTo, scrollIntoView, rootScroll } = fixture();
    expect(scrollToSettingsElement(target)).toBe(true);
    expect(scrollTo).toHaveBeenCalledWith({ top: 483, behavior: "smooth" });
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(rootScroll).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" });
  });
  it("repairs displaced document roots immediately and after browser default scrolling", () => {
    const { target, frames } = fixture();
    document.documentElement.scrollTop = 800;
    document.body.scrollTop = 800;
    scrollToSettingsElement(target);
    expect(document.documentElement.scrollTop).toBe(0);
    expect(document.body.scrollTop).toBe(0);
    document.documentElement.scrollTop = 900;
    frames[0](0);
    expect(document.documentElement.scrollTop).toBe(0);
  });
  it("retains section navigation and clamps targets above the viewport", () => {
    const { target, scrollTo } = fixture();
    vi.mocked(target.getBoundingClientRect).mockReturnValue({ top: -800 } as DOMRect);
    expect(scrollToSettingsSection(target.id, "instant")).toBe(true);
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "instant" });
  });
  it("does not scroll unrelated pages or a detail pane that has unmounted", () => {
    const { rootScroll, scrollTo } = fixture();
    expect(scrollToSettingsElement(document.createElement("div"))).toBe(false);
    expect(scrollToSettingsElement(null)).toBe(false);
    expect(scrollToSettingsSection("missing")).toBe(false);
    expect(rootScroll).not.toHaveBeenCalled();
    expect(scrollTo).not.toHaveBeenCalled();
  });
});
