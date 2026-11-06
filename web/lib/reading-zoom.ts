import { browserStorage } from "@/shared/storage";

/**
 * How big the PDF reader draws a page.
 *
 * Three answers to the same question — what does "fit" fit?
 *
 * - `text` fills the pane with the page's **text block**: the page's own white
 *   side margins are trimmed, so the type gets bigger without the page ever
 *   going wider than the pane (no horizontal scrolling while reading).
 * - `fit` fills the pane with the **page**, margins and all — the faithful
 *   view, for scans, forms, and figures that need their edges.
 * - `fixed` is an absolute percentage of the page's real size, and never
 *   trims anything: a number the reader picks must mean exactly that number.
 *
 * `text` is the default because this is a reader, not a document inspector:
 * paper margins exist for binding and thumbs, and on screen they only shrink
 * the type. It used to be a separate "crop margins" toggle, which meant two
 * controls on one axis — a page at "200%" could really be drawn at 250%, and
 * the toolbar had no way to say so.
 *
 * Kept apart from `reading-display-preferences` on purpose: those describe
 * typography shared by the text and EPUB readers, which have no page bitmap to
 * scale. Adding a zoom field there would hand both of them a value they cannot
 * honour, and would break the exact-shape assertion that test pins.
 */
export type PdfZoomPreference =
  | { mode: "text" }
  | { mode: "fit" }
  | { mode: "fixed"; scale: number };

export const PDF_ZOOM_KEY = "dt.reader.pdfZoom";
export const DEFAULT_PDF_ZOOM: PdfZoomPreference = { mode: "text" };

/** True when the page's own side margins are trimmed away. */
export function cropsPageMargins(preference: PdfZoomPreference): boolean {
  return preference.mode === "text";
}
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
 * One press of the zoom buttons or the ⌘+/⌘− shortcut, as a relative step.
 *
 * Continuous, not snapped to the menu's stops: a pinch already settles anywhere
 * (137%, say), and snapping the buttons meant the next press disagreed with the
 * size on screen — a press from 137% went *down* to 125%. The menu keeps the
 * named stops for "jump to exactly 100%", which is what stops are good for.
 */
export const PDF_ZOOM_STEP = 1.25;

export function zoomedBy(scale: number, direction: 1 | -1): number {
  const current = clampPdfZoom(scale);
  const next =
    direction === 1 ? current * PDF_ZOOM_STEP : current / PDF_ZOOM_STEP;
  // Three decimals of a ratio is finer than the toolbar's whole percent, and it
  // keeps float noise from accumulating across a run of presses.
  return clampPdfZoom(Math.round(next * 1000) / 1000);
}

/** Width in `fit` mode: word for word the pre-zoom formula. */
export function fittedPageWidth(available: number): number {
  return Math.max(MIN_PAGE_WIDTH, Math.min(MAX_FIT_PAGE_WIDTH, available));
}

/** The width one ladder stop actually lands at, budget clamp included. */
function landedWidth(
  intrinsicWidth: number,
  scale: number,
  ratio: number,
  dpr: number,
): number {
  return zoomedPageWidth(intrinsicWidth, scale, ratio, dpr);
}

/**
 * Step one stop along the ladder, skipping stops the budget collapses.
 *
 * The ladder is written in requested percentages, but the canvas budget decides
 * what lands: a 612pt page at DPR 2 cannot draw past ~1722 CSS px, so 3× and 4×
 * both land at 211%. Stepping by the requested value alone made 4×→3× change
 * nothing and wasted the first press of a climb — the reader asked for a bigger
 * page and got the same one back. This walks past every stop that lands on the
 * width already on screen, so one press always means one visible step.
 */
export function steppedPdfZoomByWidth(
  scale: number,
  direction: 1 | -1,
  intrinsicWidth: number,
  ratio: number,
  dpr: number,
): number {
  const landed = (value: number) => landedWidth(intrinsicWidth, value, ratio, dpr);
  const current = landed(scale);
  const end = direction === 1 ? MAX_PDF_ZOOM : MIN_PDF_ZOOM;
  let next = zoomedBy(scale, direction);
  // Walk while this step draws the width already on screen. The step is a
  // continuous factor here rather than a ladder, so the loop is bounded by the
  // clamp at each end: `next !== end` stops at the edge, and a factor that can
  // no longer move the scale breaks out instead of spinning.
  let guard = 0;
  while (Math.abs(landed(next) - current) < 0.5 && next !== end && guard < 64) {
    const following = zoomedBy(next, direction);
    if (following === next) break;
    next = following;
    guard += 1;
  }
  return next;
}

/**
 * Whether a step in this direction would actually change the drawn width.
 *
 * The toolbar disables a control that cannot do anything. Reading this off the
 * requested scale is wrong for the same reason the step was: at a
 * budget-clamped 3× the scale is below 4, so zoom-in looked available while
 * every press was a no-op.
 */
export function canStepPdfZoom(
  direction: 1 | -1,
  scale: number,
  intrinsicWidth: number,
  ratio: number,
  dpr: number,
  currentWidth: number,
): boolean {
  const next = steppedPdfZoomByWidth(
    scale,
    direction,
    intrinsicWidth,
    ratio,
    dpr,
  );
  return (
    Math.abs(landedWidth(intrinsicWidth, next, ratio, dpr) - currentWidth) >= 0.5
  );
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
 * The device-pixel ratio one page's canvas may actually be drawn at.
 *
 * `maxPageWidth` keeps the *shared* CSS width inside the budget using page
 * one's aspect ratio, but every page inherits that width and a page with a
 * taller aspect asks for a taller bitmap: two pages of ratio 0.75 and 2 at
 * 400% both get 3200 CSS px, and the second one asks for 3200x6400 device
 * pixels — over the budget, which the browser answers with a blank page.
 *
 * The CSS width cannot give per page: the pages share one layout width and the
 * column must not change size as you scroll. So the bitmap is what gives. The
 * ratio steps down — below 1 when it has to — and the canvas is stretched back
 * over the same CSS box, which costs sharpness on that one page instead of
 * losing it.
 */
export function canvasPixelRatio(
  cssWidth: number,
  cssHeight: number,
  requested: number,
): number {
  const dpr = Number.isFinite(requested) && requested > 0 ? requested : 1;
  const area = cssWidth * cssHeight;
  if (!(area > 0)) return dpr;
  if (area * dpr * dpr <= MAX_PAGE_CANVAS_PIXELS) return dpr;
  return Math.sqrt(MAX_PAGE_CANVAS_PIXELS / area);
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
  if (row.mode === "text") return { mode: "text" };
  if (row.mode === "fit") return { mode: "fit" };
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
