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

import { useLayoutEffect, type RefObject } from "react";

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
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const natural = el.scrollHeight;
    const bounded = Math.min(Math.max(natural, min), max);
    el.style.height = `${bounded}px`;
    el.style.overflowY = natural > max ? "auto" : "hidden";
  }, [ref, value, min, max]);
}
