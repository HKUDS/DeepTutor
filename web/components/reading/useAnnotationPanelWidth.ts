"use client";

import { useCallback, useEffect, useState } from "react";

import { browserStorage } from "@/shared/storage";

/**
 * Width of the docked annotation column, remembered per device.
 *
 * The column used to be a fixed 248px. That is a guess about how much of a
 * note is worth showing: a reader who writes paragraphs wants more, one who
 * only highlights wants the page back. The same persistence and clamping the
 * workspace's own panels use, kept in its own small hook so the reader pane
 * does not have to know about the workspace grid.
 */

const ANNOTATION_WIDTH_KEY = "dt.reader.annotationWidth";
export const ANNOTATION_MIN = 200;
export const ANNOTATION_MAX = 480;
export const ANNOTATION_DEFAULT = 248;

function clamp(value: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, value)));
}

function readStoredWidth(): number {
  if (typeof window === "undefined") return ANNOTATION_DEFAULT;
  const value = Number(browserStorage.readRaw("local", ANNOTATION_WIDTH_KEY));
  return Number.isFinite(value) && value >= ANNOTATION_MIN && value <= ANNOTATION_MAX
    ? value
    : ANNOTATION_DEFAULT;
}

export function useAnnotationPanelWidth() {
  const [width, setWidth] = useState(readStoredWidth);

  // Persist after the drag settles rather than on every pointer move: a drag
  // fires dozens of events and each write is a synchronous localStorage call.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      browserStorage.writeRaw("local", ANNOTATION_WIDTH_KEY, String(width));
    }, 150);
    return () => window.clearTimeout(timer);
  }, [width]);

  const resize = useCallback((next: number) => {
    setWidth(clamp(next, ANNOTATION_MIN, ANNOTATION_MAX));
  }, []);

  return { width, resize, min: ANNOTATION_MIN, max: ANNOTATION_MAX };
}
