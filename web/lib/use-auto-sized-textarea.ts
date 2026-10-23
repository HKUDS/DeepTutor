/**
 * Auto-grow a controlled textarea so it fits its content from a single
 * line up to a fixed maximum, after which it scrolls. Sharing one hook
 * across composers keeps their sizing behavior identical — divergent
 * imperative implementations have previously caused subtle keystroke
 * bugs (e.g. height not shrinking after Backspace on a Shift+Enter
 * line).
 *
 * The reset uses ``height: auto`` (not a fixed minimum) so the browser
 * recomputes ``scrollHeight`` from the actual content rather than from
 * a stale clipped value — that was the source of the prior shrink bug.
 */

import { useCallback, useLayoutEffect, type RefObject } from "react";

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
    // scrollHeight includes wrapped placeholder text in an empty textarea.
    // A narrow/entering reading sidebar must not turn that hint into a tall
    // empty composer. Measure the input itself, then restore the hint.
    const placeholder = el.placeholder;
    if (!el.value) el.placeholder = "";
    el.style.height = "auto";
    const natural = el.scrollHeight;
    if (!el.value) el.placeholder = placeholder;
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
