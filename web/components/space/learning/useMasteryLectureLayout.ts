"use client";

import { useCallback, useEffect, useState } from "react";

import { browserStorage } from "@/shared/storage";

const LECTURE_MIN = 320;
const CHAT_MIN = 360;
const HANDLE = 5;
/** Below this the two panes stop being readable side by side. */
const SPLIT_MIN_FRAME = 900;

const STORAGE_KEY = "dt.mastery.lectureWidth";

const clamp = (value: number, min: number, max: number) =>
  Math.round(Math.min(max, Math.max(min, value)));

function readWidth(fallback: number) {
  if (typeof window === "undefined") return fallback;
  const value = Number(browserStorage.readRaw("local", STORAGE_KEY));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

/**
 * The review screen's two panes: the lecture, and the conversation about it.
 *
 * Unlike the reading workspace this is deliberately *not* a three-pane model.
 * Review has exactly two things in it and the learner is meant to read one
 * while talking about the other, so the chat keeps the larger share and the
 * lecture gets whatever width the learner gives it — remembered, because
 * choosing it again on every point is pure friction.
 */
export function useMasteryLectureLayout({ enabled }: { enabled: boolean }) {
  const [element, gridAttach] = useState<HTMLDivElement | null>(null);
  const [frame, setFrame] = useState(0);
  const [preferred, setPreferred] = useState(() => readWidth(420));
  const [collapsed, setCollapsed] = useState(false);

  // A callback ref, not an effect on a node: the grid only exists once the
  // point's lecture has loaded, which is after the first paint.
  useEffect(() => {
    if (!element) return;
    const measure = () => setFrame(element.clientWidth);
    const scheduled = requestAnimationFrame(measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    if (!observer) window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(scheduled);
      observer?.disconnect();
      if (!observer) window.removeEventListener("resize", measure);
    };
  }, [element]);

  const split = enabled && frame > 0 && frame >= SPLIT_MIN_FRAME && !collapsed;
  // The lecture may shrink to its floor, but never below the point where the
  // chat would be squeezed past its own minimum.
  const lectureMax = Math.max(LECTURE_MIN, frame - CHAT_MIN - HANDLE);
  const lectureWidth = split ? clamp(preferred, LECTURE_MIN, lectureMax) : 0;

  const resize = useCallback((width: number) => {
    setPreferred(clamp(width, LECTURE_MIN, 2400));
    browserStorage.writeRaw("local", STORAGE_KEY, String(clamp(width, LECTURE_MIN, 2400)));
  }, []);

  const toggle = useCallback(() => setCollapsed((value) => !value), []);

  return {
    gridAttach,
    /** Only set once the frame is measured; undefined keeps CSS in charge. */
    gridStyle: split
      ? { gridTemplateColumns: `${lectureWidth}px ${HANDLE}px minmax(0,1fr)` }
      : undefined,
    split,
    collapsed,
    lectureWidth,
    lectureMin: LECTURE_MIN,
    lectureMax,
    resize,
    toggle,
    handleWidth: HANDLE,
  };
}
