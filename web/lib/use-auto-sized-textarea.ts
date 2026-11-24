/**
 * Auto-grow a controlled textarea so it fits its content from a single
 * line up to a fixed maximum, after which it scrolls. Sharing one hook
 * across composers keeps their sizing behavior identical — divergent
 * imperative implementations have previously caused subtle keystroke
 * bugs (e.g. height not shrinking after Backspace on a Shift+Enter
 * line).
 *
 * Measure an out-of-flow textarea instead of resetting the live field.
 * Even a temporary shrink can clamp a sibling chat's scrollTop; restoring
 * the field's height does not restore that position, so the next streamed
 * update pulls the messages back down and makes them jitter while typing.
 */

import { useCallback, useLayoutEffect, type RefObject } from "react";

const MEASUREMENT_STYLES = [
  "box-sizing", "width", "font-family", "font-size", "font-weight",
  "font-style", "font-stretch", "font-variant", "font-feature-settings",
  "font-variation-settings", "line-height", "letter-spacing", "word-spacing",
  "text-indent", "text-transform", "text-align", "direction", "tab-size",
  "white-space", "word-break", "overflow-wrap",
  "padding-top", "padding-right", "padding-bottom", "padding-left",
  "border-top-width", "border-right-width", "border-bottom-width",
  "border-left-width", "border-style",
] as const;

function measureContentHeight(el: HTMLTextAreaElement): number {
  const doc = el.ownerDocument;
  const computed = doc.defaultView!.getComputedStyle(el);
  const mirror = doc.createElement("textarea");
  mirror.rows = el.rows;
  mirror.wrap = el.wrap;
  mirror.value = el.value;
  mirror.tabIndex = -1;
  mirror.setAttribute("aria-hidden", "true");
  for (const property of MEASUREMENT_STYLES) {
    mirror.style.setProperty(property, computed.getPropertyValue(property));
  }
  // No placeholder: wrapped hint text must not grow an empty composer.
  // Copy computed styles because a body-level mirror has different ancestors.
  Object.assign(mirror.style, {
    position: "fixed", left: "-10000px", top: "0", visibility: "hidden",
    height: "auto", minHeight: "0", maxHeight: "none",
    minWidth: "0", maxWidth: "none", overflow: "hidden",
    transition: "none", pointerEvents: "none",
  });
  doc.body.appendChild(mirror);
  try {
    return mirror.scrollHeight;
  } finally {
    mirror.remove();
  }
}

export interface AutoSizedTextareaOptions {
  /** Minimum height in pixels (clamps ``scrollHeight`` from below). */
  min?: number;
  /** Maximum height in pixels; beyond this the textarea scrolls. */
  max?: number;
}

export function useAutoSizedTextarea(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  { min = 0, max = Number.POSITIVE_INFINITY }: AutoSizedTextareaOptions = {},
): void {
  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const natural = measureContentHeight(el);
    const bounded = Math.min(Math.max(natural, min), max);
    el.style.height = `${bounded}px`;
    el.style.overflowY = natural > max ? "auto" : "hidden";
  }, [ref, min, max]);

  useLayoutEffect(resize, [resize, value]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let previousWidth: number | undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const width = entry.contentRect.width;
      // Ignore height notifications caused by our own measurement, but keep
      // track of hidden panels so reopening at the same width remeasures.
      if (width === previousWidth) return;
      previousWidth = width;
      if (width > 0) resize();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, resize]);
}
