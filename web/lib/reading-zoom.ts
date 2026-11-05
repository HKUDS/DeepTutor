import { browserStorage } from "@/shared/storage";

/**
 * How big the PDF reader draws a page.
 *
 * `fit` is the reader's historical behaviour — the page fills the pane's
 * width — and `fixed` is an absolute percentage of the page's real size.
 *
 * Kept apart from `reading-display-preferences` on purpose: those describe
 * typography shared by the text and EPUB readers, which have no page bitmap to
 * scale. Adding a zoom field there would hand both of them a value they cannot
 * honour, and would break the exact-shape assertion that test pins.
 */
export type PdfZoomPreference =
  { mode: "fit" } | { mode: "fixed"; scale: number };

export const PDF_ZOOM_KEY = "dt.reader.pdfZoom";
export const DEFAULT_PDF_ZOOM: PdfZoomPreference = { mode: "fit" };
export const MIN_PDF_ZOOM = 0.25;
export const MAX_PDF_ZOOM = 4;

/** The stops the menu offers, in ascending order. */
export const PDF_ZOOM_OPTIONS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

/**
 * PDF user-space units are points (1/72"), CSS pixels are 1/96", so a page at
 * "100%" is 96/72 of its `scale: 1` width.
 *
 * This is the same reading Acrobat and the system Preview show, and it is the
 * difference between "100%" meaning the page's real size and "100%" meaning
 * "the size pdf.js happens to hand back".
 */
export const ACTUAL_SIZE_FACTOR = 96 / 72;

/**
 * Device-pixel budget for one page's canvas.
 *
 * Safari drops a bitmap past roughly 16.7M device pixels — silently, as a
 * blank page rather than an error — and the same ceiling is what keeps a 400%
 * zoom on a tall page from asking for a canvas the browser will refuse.
 */
export const MAX_PAGE_CANVAS_PIXELS = 16_777_216;

/** Side padding of the reading pane, matching the pre-zoom width formula. */
export const READER_WIDTH_INSET = 48;
export const MIN_PAGE_WIDTH = 240;
export const MAX_FIT_PAGE_WIDTH = 1100;

export function clampPdfZoom(scale: number): number {
  if (!Number.isFinite(scale)) return 1;
  return Math.min(MAX_PDF_ZOOM, Math.max(MIN_PDF_ZOOM, scale));
}

/**
 * Step one stop along the menu's ladder.
 *
 * A ladder rather than "current ±25%": a pinch settles wherever the gesture
 * ends — 1.37, say — and only discrete stops keep the displayed percentage,
 * the checked menu row and what the next press produces all describing the
 * same size.
 */
export function steppedPdfZoom(scale: number, direction: 1 | -1): number {
  const current = clampPdfZoom(scale);
  if (direction === 1) {
    return (
      PDF_ZOOM_OPTIONS.find((value) => value > current + 1e-6) ?? MAX_PDF_ZOOM
    );
  }
  return (
    [...PDF_ZOOM_OPTIONS].reverse().find((value) => value < current - 1e-6) ??
    MIN_PDF_ZOOM
  );
}

/** Width in `fit` mode: word for word the pre-zoom formula. */
export function fittedPageWidth(available: number): number {
  return Math.max(MIN_PAGE_WIDTH, Math.min(MAX_FIT_PAGE_WIDTH, available));
}

/** The page's CSS width at "100%". */
export function actualSizeWidth(intrinsicWidth: number): number {
  return intrinsicWidth > 0 ? intrinsicWidth * ACTUAL_SIZE_FACTOR : 0;
}

/** Largest CSS width one page may take at a given aspect ratio and DPR. */
export function maxPageWidth(ratio: number, dpr: number): number {
  const safeRatio = ratio > 0 ? ratio : 1.414;
  const safeDpr = Math.max(1, dpr);
  return Math.floor(
    Math.sqrt(MAX_PAGE_CANVAS_PIXELS / (safeRatio * safeDpr * safeDpr)),
  );
}

/**
 * Width in `fixed` mode: 100% is the page's real CSS size, clamped to the
 * canvas budget so a tall page never asks for a bitmap the browser drops.
 */
export function zoomedPageWidth(
  intrinsicWidth: number,
  scale: number,
  ratio: number,
  dpr: number,
): number {
  const target = actualSizeWidth(intrinsicWidth) * clampPdfZoom(scale);
  return Math.max(MIN_PAGE_WIDTH, Math.min(maxPageWidth(ratio, dpr), target));
}

/**
 * The percentage the toolbar shows: the width that actually landed over the
 * 100% width.
 *
 * When the canvas budget clamps a 400% request to 215%, the reader is told
 * 215% rather than a number the reader cannot deliver.
 */
export function effectiveZoomPercent(
  pageWidth: number,
  intrinsicWidth: number,
): number {
  const actual = actualSizeWidth(intrinsicWidth);
  if (actual <= 0 || pageWidth <= 0) return 100;
  return Math.round((pageWidth / actual) * 100);
}

/**
 * The ratio a `fit` page is actually drawn at, used as the starting point for
 * "zoom in one stop".
 *
 * Clamped to the floor: a wide page fitted into a narrow pane can sit below
 * 25%, and starting from there would make the first press jump up instead of
 * landing one stop larger than what the reader is looking at.
 */
export function fitZoomRatio(
  pageWidth: number,
  intrinsicWidth: number,
): number {
  const actual = actualSizeWidth(intrinsicWidth);
  if (actual <= 0 || pageWidth <= 0) return 1;
  return clampPdfZoom(pageWidth / actual);
}

export function normalisePdfZoom(value: unknown): PdfZoomPreference {
  const row =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  if (
    row.mode === "fixed" &&
    typeof row.scale === "number" &&
    Number.isFinite(row.scale)
  ) {
    return { mode: "fixed", scale: clampPdfZoom(row.scale) };
  }
  return DEFAULT_PDF_ZOOM;
}

export function loadPdfZoom(): PdfZoomPreference {
  try {
    return normalisePdfZoom(
      JSON.parse(browserStorage.readRaw("local", PDF_ZOOM_KEY) || "{}"),
    );
  } catch {
    return DEFAULT_PDF_ZOOM;
  }
}

export function savePdfZoom(preference: PdfZoomPreference): void {
  browserStorage.writeRaw("local", PDF_ZOOM_KEY, JSON.stringify(preference));
}

export type PdfZoomShortcut = "increase" | "decrease" | "reset";

/**
 * The same shape as `readerDisplayShortcut`, but scoped to the PDF view.
 *
 * The text and EPUB readers bind `⌘+`/`⌘−` to font size; the PDF view does not
 * mount that handler at all, so the two never fight over the same chord.
 */
export function pdfZoomShortcut(input: {
  key: string;
  modifier: boolean;
  readerHovered: boolean;
  readerFocused: boolean;
}): PdfZoomShortcut | null {
  if (!input.modifier || (!input.readerHovered && !input.readerFocused)) {
    return null;
  }
  if (input.key === "+" || input.key === "=") return "increase";
  if (input.key === "-") return "decrease";
  if (input.key === "0") return "reset";
  return null;
}
