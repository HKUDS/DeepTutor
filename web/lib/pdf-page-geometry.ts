/**
 * Geometry helpers for the PDF reader: where the ink actually sits on a page,
 * and where the pictures are.
 *
 * The reader lays every page out at the pane's width, which leaves the page's
 * own white side margins on screen twice over — the document's margins plus the
 * pane's padding. Measuring the ink bounding box lets the reader zoom until the
 * text block fills the pane instead.
 */

/**
 * The slice of pdf.js's page proxy these helpers need.
 *
 * Declared locally rather than imported so that the node test runner, which
 * compiles only what it is given, can type-check this module without dragging
 * pdf.js — and its `import.meta` — into the test build.
 */
export interface PdfPageGeometrySource {
  getViewport(parameters: { scale: number }): {
    width: number;
    height: number;
    transform: number[];
  };
}

/** A page that can also be painted, which is what measuring the ink needs. */
export interface PdfPageMeasureSource extends PdfPageGeometrySource {
  render: unknown;
}

export interface NormalisedBox {
  /** Left edge as a fraction of the page width. */
  x0: number;
  /** Top edge as a fraction of the page height. */
  y0: number;
  x1: number;
  y1: number;
}

/** A box covering the whole page — what "no cropping" means. */
export const FULL_PAGE_BOX: NormalisedBox = { x0: 0, y0: 0, x1: 1, y1: 1 };

/** Width used for the throwaway render the ink box is measured from. */
const SAMPLE_WIDTH = 200;
/** Pixels lighter than this (average luma) count as paper, not ink. */
const PAPER_LUMA = 236;
/** A column must hold at least this share of the densest column to be content. */
const COLUMN_SHARE = 0.05;
/** Never zoom so far that less than this share of the page survives. */
const MIN_CONTENT_WIDTH = 0.42;
/**
 * When the ink already covers this much of the page, there is nothing to trim.
 *
 * A contents page, a full-width table, a slide: their text block reaches the
 * page's own margins, so cropping would gain a few percent while putting the
 * last glyph on the cut. Fit-the-page is the honest answer for those.
 */
const MAX_CONTENT_WIDTH = 0.92;
/** Never trim more than this from one side, however empty it looks. */
const MAX_MARGIN = 0.24;
/**
 * Paper kept on each side of the text block, as a share of the page width.
 *
 * Cropping exactly to the ink puts the text hard against the edge of the
 * visible strip — and a page whose ink reaches its own margins (a table of
 * contents, a table rule, a full-width figure) then reads as if it had been
 * cut off: the numbers sit on the cut, with a pixel of paper beside them. Two
 * percent of an A4 page is about 4mm, which looks like a page margin and costs
 * almost none of the zoom.
 */
const CROP_PADDING = 0.02;

/** Cache keyed by `materialId:locator`; `null` means "measured, nothing to crop". */
const inkBoxes = new Map<string, NormalisedBox | null>();
const inkBoxRequests = new Map<string, Promise<NormalisedBox | null>>();
/** Keeps a very long PDF's measurements from growing without bound. */
const INK_CACHE_LIMIT = 2048;

/**
 * Left and right extent of the ink on a rendered page.
 *
 * Only the horizontal axis is cropped: the reading pane scrolls vertically, so
 * trimming the top and bottom too would simply make pages shorter than the
 * viewport and gain nothing.
 *
 * Sparse columns — a page number tucked into the gutter, a hairline rule — are
 * ignored by requiring a column to reach `COLUMN_SHARE` of the densest column,
 * which is what keeps the crop anchored to the text block rather than to the
 * most decorative thing on the page.
 */
export function inkBoxFromPixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): NormalisedBox | null {
  if (width <= 0 || height <= 0) return null;
  const columns = new Uint32Array(width);
  let densest = 0;
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * width;
    for (let x = 0; x < width; x += 1) {
      const index = (rowStart + x) * 4;
      if (pixels[index + 3] < 32) continue;
      const luma =
        (pixels[index] * 299 + pixels[index + 1] * 587 + pixels[index + 2] * 114) /
        1000;
      if (luma >= PAPER_LUMA) continue;
      columns[x] += 1;
      if (columns[x] > densest) densest = columns[x];
    }
  }
  if (densest === 0) return null;

  const threshold = Math.max(1, Math.round(densest * COLUMN_SHARE));
  let left = -1;
  let right = -1;
  for (let x = 0; x < width; x += 1) {
    if (columns[x] < threshold) continue;
    if (left < 0) left = x;
    right = x;
  }
  if (left < 0 || right < 0) return null;

  const detected = right + 1 - left;
  const share = detected / width;
  if (share < MIN_CONTENT_WIDTH) return null;
  if (share > MAX_CONTENT_WIDTH) return null;

  // Keep a sliver of paper outside the ink so the text block does not end
  // exactly on the cut. `MAX_MARGIN` still caps how much one side may lose.
  const x0 = Math.min(MAX_MARGIN, Math.max(0, left / width - CROP_PADDING));
  const x1 = Math.max(
    1 - MAX_MARGIN,
    Math.min(1, (right + 1) / width + CROP_PADDING),
  );
  return { x0, y0: 0, x1, y1: 1 };
}

/** Aspect-preserving layout for one page, cropped to `box` when there is one. */
export interface CropLayout {
  /** CSS width of the visible strip. */
  visibleWidth: number;
  /** CSS width of the whole page, of which only part is shown. */
  fullWidth: number;
  /** CSS height of the page — cropping never touches the vertical axis. */
  fullHeight: number;
  /** How far the page is pushed left, in CSS pixels. */
  offsetX: number;
}

export function cropLayout(
  pageWidth: number,
  ratio: number,
  box: NormalisedBox | null,
): CropLayout {
  const width = Math.max(1, Math.round(pageWidth));
  const fraction = box
    ? Math.min(1, Math.max(MIN_CONTENT_WIDTH, box.x1 - box.x0))
    : 1;
  const fullWidth = Math.max(width, Math.round(width / fraction));
  return {
    visibleWidth: width,
    fullWidth,
    fullHeight: Math.round(fullWidth * ratio),
    offsetX: box ? Math.round(Math.min(0.5, Math.max(0, box.x0)) * fullWidth) : 0,
  };
}

/**
 * Ink box of one page, measured once per material and remembered.
 *
 * Measurement renders the page into a 200px-wide scratch canvas rather than
 * reading the operator list: a page that paints a white rectangle behind its
 * text — which most do — would report a full-page box from the operators alone,
 * while the pixels show where the text actually stops.
 */
export async function measurePageInkBox(
  page: PdfPageMeasureSource,
  key: string,
): Promise<NormalisedBox | null> {
  if (inkBoxes.has(key)) return inkBoxes.get(key) ?? null;
  const inflight = inkBoxRequests.get(key);
  if (inflight) return inflight;

  const request = measureInkBox(page).then(
    (box) => {
      if (inkBoxes.size >= INK_CACHE_LIMIT) inkBoxes.clear();
      inkBoxes.set(key, box);
      inkBoxRequests.delete(key);
      return box;
    },
    () => {
      inkBoxRequests.delete(key);
      return null;
    },
  );
  inkBoxRequests.set(key, request);
  return request;
}

async function measureInkBox(page: PdfPageMeasureSource): Promise<NormalisedBox | null> {
  const canvas = document.createElement("canvas");
  const base = page.getViewport({ scale: 1 });
  if (!(base.width > 0)) return null;
  const viewport = page.getViewport({ scale: SAMPLE_WIDTH / base.width });
  canvas.width = Math.max(1, Math.ceil(viewport.width));
  canvas.height = Math.max(1, Math.ceil(viewport.height));
  // Headless DOMs (and locked-down webviews) hand back no context; there is
  // nothing to measure then, and the reader simply shows the whole page.
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  // `render` is reached through a cast because the real signature pins the
  // viewport to pdf.js's own `PageViewport`; this module deliberately does not
  // depend on pdf.js so the test build stays free of its `import.meta`.
  //
  // Called as a method, never pulled into a local first: `PDFPageProxy.render`
  // reads `this._transport` and `this._stats`, so an unbound call throws
  // "Cannot read properties of undefined (reading '_stats')" — and because the
  // caller treats a failed measurement as "nothing to crop", every page would
  // silently fall back to the full width instead of failing loudly.
  const renderPage = page.render as (
    this: PdfPageMeasureSource,
    parameters: {
      canvas: HTMLCanvasElement;
      viewport: { width: number; height: number; transform: number[] };
    },
  ) => { promise: Promise<void> };
  await renderPage.call(page, { canvas, viewport }).promise;
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
  return inkBoxFromPixels(data, canvas.width, canvas.height);
}
