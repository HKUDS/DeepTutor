/**
 * Selection geometry: browser client rects → normalised annotation rects.
 *
 * Everything here is pure so it can be tested without a DOM: callers pass the
 * rectangles they already measured. The output space is the one the store and
 * the PDF export both speak — 0..1 of the unit box, origin top-left.
 *
 * Two behaviours are worth stating, because both were failure modes in the
 * hand-rolled version:
 *
 * * **Line merging.** A selection spanning a wrapped phrase yields one client
 *   rect per line, plus slivers where the range clips a character box. Slivers
 *   render as visual noise, so rects are merged per text line and the
 *   degenerate ones dropped.
 * * **Clamping.** A drag that leaves the page produces rects outside the box.
 *   They are clipped rather than discarded, so the highlight still covers the
 *   part of the text that *is* on the page.
 */

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export type NormalisedRect = [number, number, number, number];

/** Rects thinner or shorter than this (in px) are selection artefacts. */
const MIN_RECT_PX = 2;
/** Vertical overlap ratio above which two rects count as the same line. */
const SAME_LINE_OVERLAP = 0.5;

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/**
 * Group rects into text lines by vertical overlap, then union each group.
 *
 * Overlap rather than equal tops: sub/superscripts and mixed font sizes on one
 * line have different tops but clearly belong together.
 */
export function mergeRectsByLine(rects: Box[]): Box[] {
  const usable = rects.filter(
    (rect) => rect.width >= MIN_RECT_PX && rect.height >= MIN_RECT_PX,
  );
  if (!usable.length) return [];

  const sorted = [...usable].sort((a, b) => a.top - b.top || a.left - b.left);
  const lines: Box[][] = [];
  for (const rect of sorted) {
    const line = lines.find((candidate) => {
      const probe = candidate[0];
      const overlap =
        Math.min(probe.top + probe.height, rect.top + rect.height) -
        Math.max(probe.top, rect.top);
      const shorter = Math.min(probe.height, rect.height);
      return shorter > 0 && overlap / shorter >= SAME_LINE_OVERLAP;
    });
    if (line) line.push(rect);
    else lines.push([rect]);
  }

  return lines.map((line) => {
    const left = Math.min(...line.map((r) => r.left));
    const top = Math.min(...line.map((r) => r.top));
    const right = Math.max(...line.map((r) => r.left + r.width));
    const bottom = Math.max(...line.map((r) => r.top + r.height));
    return { left, top, width: right - left, height: bottom - top };
  });
}

/**
 * Convert client rects to normalised rects relative to *container*.
 *
 * Both inputs are viewport-space rects (what `getBoundingClientRect` returns),
 * so scroll position cancels out and no scroll offset is needed.
 */
export function normaliseRects(rects: Box[], container: Box): NormalisedRect[] {
  if (container.width <= 0 || container.height <= 0) return [];
  return mergeRectsByLine(rects)
    .map((rect): NormalisedRect => {
      const x0 = clamp01((rect.left - container.left) / container.width);
      const y0 = clamp01((rect.top - container.top) / container.height);
      const x1 = clamp01(
        (rect.left + rect.width - container.left) / container.width,
      );
      const y1 = clamp01(
        (rect.top + rect.height - container.top) / container.height,
      );
      return [
        Math.min(x0, x1),
        Math.min(y0, y1),
        Math.max(x0, x1),
        Math.max(y0, y1),
      ];
    })
    .filter(([x0, y0, x1, y1]) => x1 - x0 > 0.001 && y1 - y0 > 0.001);
}

/** Union of normalised rects, for positioning a popover over a selection. */
export function unionRect(rects: NormalisedRect[]): NormalisedRect | null {
  if (!rects.length) return null;
  return [
    Math.min(...rects.map((r) => r[0])),
    Math.min(...rects.map((r) => r[1])),
    Math.max(...rects.map((r) => r[2])),
    Math.max(...rects.map((r) => r[3])),
  ];
}

/**
 * Tidy a selected string for storage as a quote.
 *
 * pdf.js text layers introduce line breaks wherever the PDF did, so the raw
 * selection is full of hard wraps. Collapsing them is what makes the quote
 * match the stored unit text server-side — the verification step that gates
 * `reader_goto` depends on it.
 */
export function cleanQuote(raw: string, limit = 2000): string {
  const flat = (raw || "").replace(/\s+/g, " ").trim();
  return flat.length <= limit ? flat : flat.slice(0, limit);
}

/**
 * Which locator a selection belongs to, given the elements it spans.
 *
 * A selection dragged across a page boundary is attributed to where it
 * *started*, matching how the user thinks about it, instead of being rejected.
 */
export function locatorOfSelection(
  locators: Array<number | null>,
): number | null {
  for (const locator of locators) {
    if (typeof locator === "number" && locator >= 1) return locator;
  }
  return null;
}
