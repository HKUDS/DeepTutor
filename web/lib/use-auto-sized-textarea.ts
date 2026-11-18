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
 *
 * Measuring used to create/destroy a mirror on every keystroke and copy a
 * full computed-style snapshot each time. On a KaTeX-heavy chat that layout
 * work dominated ComposerInput commits (hundreds of ms Layout effects in
 * Firefox — #2745 / #2743). Reuse one mirror per document, refresh styles
 * only when width changes, skip no-op height writes, and defer while IME
 * composition is active.
 */

import { useCallback, useLayoutEffect, useRef, type RefObject } from "react";

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

type MirrorState = {
  mirror: HTMLTextAreaElement;
  styleWidth: number;
};

const mirrorsByDocument = new WeakMap<Document, MirrorState>();

function mirrorFor(doc: Document): MirrorState {
  let state = mirrorsByDocument.get(doc);
  if (state && state.mirror.isConnected) return state;

  const mirror = doc.createElement("textarea");
  mirror.tabIndex = -1;
  mirror.setAttribute("aria-hidden", "true");
  // No placeholder: wrapped hint text must not grow an empty composer.
  Object.assign(mirror.style, {
    position: "fixed", left: "-10000px", top: "0", visibility: "hidden",
    height: "auto", minHeight: "0", maxHeight: "none",
    minWidth: "0", maxWidth: "none", overflow: "hidden",
    transition: "none", pointerEvents: "none",
  });
  doc.body.appendChild(mirror);
  state = { mirror, styleWidth: Number.NaN };
  mirrorsByDocument.set(doc, state);
  return state;
}

function syncMirrorStyles(
  el: HTMLTextAreaElement,
  state: MirrorState,
  width: number,
): void {
  if (state.styleWidth === width) return;
  state.styleWidth = width;
  const computed = el.ownerDocument.defaultView!.getComputedStyle(el);
  for (const property of MEASUREMENT_STYLES) {
    state.mirror.style.setProperty(property, computed.getPropertyValue(property));
  }
  state.mirror.rows = el.rows;
  state.mirror.wrap = el.wrap;
}

function measureContentHeight(el: HTMLTextAreaElement): number {
  const width = el.offsetWidth;
  const state = mirrorFor(el.ownerDocument);
  // Hidden panels report width 0; still measure value against cached styles
  // so clears/sends shrink the field. Visible fields refresh styles when
  // width changes (sidebar drag, etc.).
  if (width > 0) {
    syncMirrorStyles(el, state, width);
    state.mirror.style.width = `${width}px`;
  } else if (Number.isNaN(state.styleWidth)) {
    syncMirrorStyles(el, state, 0);
  }
  state.mirror.value = el.value;
  return state.mirror.scrollHeight;
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
  const composingRef = useRef(false);
  const pendingResizeRef = useRef(false);
  const rafRef = useRef(0);

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const natural = measureContentHeight(el);
    const bounded = Math.min(Math.max(natural, min), max);
    const nextHeight = `${bounded}px`;
    const nextOverflow = natural > max ? "auto" : "hidden";
    // Avoid style writes that invalidate layout when nothing changed.
    if (el.style.height !== nextHeight) el.style.height = nextHeight;
    if (el.style.overflowY !== nextOverflow) el.style.overflowY = nextOverflow;
  }, [ref, min, max]);

  const scheduleResize = useCallback(() => {
    if (composingRef.current) {
      pendingResizeRef.current = true;
      return;
    }
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      resize();
    });
  }, [resize]);

  useLayoutEffect(() => {
    scheduleResize();
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }
    };
  }, [scheduleResize, value]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onCompositionStart = () => {
      composingRef.current = true;
    };
    const onCompositionEnd = () => {
      composingRef.current = false;
      if (pendingResizeRef.current) {
        pendingResizeRef.current = false;
        scheduleResize();
      }
    };
    el.addEventListener("compositionstart", onCompositionStart);
    el.addEventListener("compositionend", onCompositionEnd);
    return () => {
      el.removeEventListener("compositionstart", onCompositionStart);
      el.removeEventListener("compositionend", onCompositionEnd);
    };
  }, [ref, scheduleResize]);

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
      if (width > 0) {
        // Width changes must apply before paint; do not wait for a frame.
        if (rafRef.current) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = 0;
        }
        resize();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, resize]);
}
