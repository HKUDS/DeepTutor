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
  getOperatorList?(): Promise<{
    fnArray: number[];
    argsArray: unknown[];
  }>;
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
 * How long a measurement may take before the page is drawn uncropped.
 *
 * Some embedded browsers paint a page but never settle the render promise (the
 * reason the canvas paint was decoupled from it). Without a bound, the "not
 * measured yet" state never ends: the canvas is never painted at all, and the
 * hung promise stays in `inkBoxRequests` for the life of the tab, so a remount
 * gets the same dead promise back. Failing to "no crop" is the honest answer —
 * the reader sees the whole page, which is what the mode did before.
 */
export const INK_MEASURE_TIMEOUT_MS = 1000;

/** Race a measurement against the timeout, resolving `null` when it loses. */
function withInkTimeout(
  measurement: Promise<NormalisedBox | null>,
): Promise<NormalisedBox | null> {
  return new Promise<NormalisedBox | null>((resolve) => {
    const timer = setTimeout(() => resolve(null), INK_MEASURE_TIMEOUT_MS);
    const settle = (value: NormalisedBox | null) => {
      clearTimeout(timer);
      resolve(value);
    };
    measurement.then(settle, () => settle(null));
  });
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

  const request = withInkTimeout(measureInkBox(page)).then(
    (box) => {
      // `null` from a TIMEOUT is not an answer, so it is not remembered: a
      // remount (or a second attempt) should measure again rather than inherit
      // "this page has nothing to crop" from a browser that never replied.
      if (box !== null) {
        if (inkBoxes.size >= INK_CACHE_LIMIT) inkBoxes.clear();
        inkBoxes.set(key, box);
      }
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

type Matrix = [number, number, number, number, number, number];

const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];
/** Picture boxes smaller than this share of the page are not worth a hotspot. */
const MIN_IMAGE_AREA = 0.003;
/** A hotspot that covers the page is a scan; still useful, but keep just one. */
const MAX_HOTSPOTS = 60;

function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

function apply(m: Matrix, x: number, y: number): [number, number] {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/**
 * Boxes of the images a page paints, in page-normalised coordinates.
 *
 * A PDF page is one bitmap by the time it reaches the DOM, so there is no
 * element to click. The operator list still knows where each image was placed:
 * `paintImageXObject` draws the unit square through the current transformation
 * matrix, so replaying save/restore/transform/form-object pairing recovers the
 * rectangle each picture covers.
 */
export function imageBoxesFromOperatorList(
  list: { fnArray: number[]; argsArray: unknown[] },
  ops: Readonly<Record<string, number>>,
  viewport: { width: number; height: number; transform: number[] },
): NormalisedBox[] {
  const paintImage = new Set(
    [
      ops.paintImageXObject,
      ops.paintInlineImageXObject,
      ops.paintImageMaskXObject,
    ].filter((value): value is number => typeof value === "number"),
  );
  if (!paintImage.size) return [];

  const stack: Matrix[] = [];
  let ctm: Matrix = IDENTITY;
  const boxes: NormalisedBox[] = [];

  for (let index = 0; index < list.fnArray.length; index += 1) {
    const fn = list.fnArray[index];
    const args = list.argsArray[index];
    if (fn === ops.save) {
      stack.push([...ctm] as Matrix);
      continue;
    }
    if (fn === ops.restore) {
      ctm = stack.pop() ?? IDENTITY;
      continue;
    }
    if (fn === ops.transform) {
      ctm = multiply(ctm, args as Matrix);
      continue;
    }
    if (fn === ops.paintFormXObjectBegin) {
      stack.push([...ctm] as Matrix);
      // A form with no Matrix entry is legal — pdf.js reports `null` for it,
      // and generators emit them. An omitted Matrix means the identity, so
      // multiplying by it must be a no-op; multiplying by `null` throws, and
      // the caller treats the throw as "this page has no pictures", which
      // dropped every hotspot on the page, including the ones outside the
      // form.
      const formMatrix = (args as [Matrix | null | undefined, unknown] | null)?.[0];
      ctm = multiply(ctm, formMatrix ?? IDENTITY);
      continue;
    }
    if (fn === ops.paintFormXObjectEnd) {
      ctm = stack.pop() ?? IDENTITY;
      continue;
    }
    if (!paintImage.has(fn)) continue;

    const corners = [
      apply(ctm, 0, 0),
      apply(ctm, 1, 0),
      apply(ctm, 0, 1),
      apply(ctm, 1, 1),
    ].map(([x, y]) => {
      const [px, py] = apply(viewport.transform as Matrix, x, y);
      return { x: px / viewport.width, y: py / viewport.height };
    });
    const xs = corners.map((corner) => corner.x);
    const ys = corners.map((corner) => corner.y);
    const box: NormalisedBox = {
      x0: Math.max(0, Math.min(...xs)),
      y0: Math.max(0, Math.min(...ys)),
      x1: Math.min(1, Math.max(...xs)),
      y1: Math.min(1, Math.max(...ys)),
    };
    if (box.x1 - box.x0 <= 0 || box.y1 - box.y0 <= 0) continue;
    if ((box.x1 - box.x0) * (box.y1 - box.y0) < MIN_IMAGE_AREA) continue;
    boxes.push(box);
  }

  // Duplicates arise from masks painted on top of their own picture; keeping
  // the first of each rounded rectangle is enough for a click target.
  const seen = new Set<string>();
  return boxes
    .filter((box) => {
      const key = [box.x0, box.y0, box.x1, box.y1]
        .map((value) => value.toFixed(2))
        .join(":");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort(
      (a, b) =>
        (b.x1 - b.x0) * (b.y1 - b.y0) - (a.x1 - a.x0) * (a.y1 - a.y0),
    )
    .slice(0, MAX_HOTSPOTS);
}

/** Image boxes for one page, or nothing when the page has no pictures. */
export async function pageImageBoxes(
  page: PdfPageGeometrySource,
  ops: Readonly<Record<string, number>> | undefined,
): Promise<NormalisedBox[]> {
  if (!ops || typeof page.getOperatorList !== "function") return [];
  try {
    const list = await page.getOperatorList();
    const viewport = page.getViewport({ scale: 1 });
    return imageBoxesFromOperatorList(
      { fnArray: [...list.fnArray], argsArray: [...list.argsArray] },
      ops,
      {
        width: viewport.width,
        height: viewport.height,
        transform: viewport.transform as number[],
      },
    );
  } catch {
    return [];
  }
}
