import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ACTUAL_SIZE_FACTOR,
  DEFAULT_PDF_ZOOM,
  cropsPageMargins,
  MAX_FIT_PAGE_WIDTH,
  MAX_PDF_ZOOM,
  MAX_PAGE_CANVAS_PIXELS,
  MIN_PAGE_WIDTH,
  MIN_PDF_ZOOM,
  PDF_ZOOM_OPTIONS,
  actualSizeWidth,
  clampPdfZoom,
  effectiveZoomPercent,
  fitZoomRatio,
  fittedPageWidth,
  maxPageWidth,
  normalisePdfZoom,
  pdfZoomShortcut,
  canStepPdfZoom,
  PDF_ZOOM_KEY,
  type PdfZoomPreference,
  steppedPdfZoomByWidth,
  zoomedBy,
  zoomedPageWidth,
} from "../lib/reading-zoom";


test("fit width is the pre-zoom formula, unchanged", () => {
  // The whole feature has to leave the default layout bit-for-bit identical:
  // this is the formula the reader shipped with.
  assert.equal(fittedPageWidth(600), 600);
  assert.equal(fittedPageWidth(2000), MAX_FIT_PAGE_WIDTH);
  assert.equal(fittedPageWidth(100), MIN_PAGE_WIDTH);
  assert.equal(MIN_PAGE_WIDTH, 240);
  assert.equal(MAX_FIT_PAGE_WIDTH, 1100);
});

test("zoom is clamped to the supported range", () => {
  assert.equal(MIN_PDF_ZOOM, 0.25);
  assert.equal(MAX_PDF_ZOOM, 4);
  assert.equal(clampPdfZoom(0.01), MIN_PDF_ZOOM);
  assert.equal(clampPdfZoom(99), MAX_PDF_ZOOM);
  assert.equal(clampPdfZoom(Number.NaN), 1);
  assert.equal(clampPdfZoom(Number.POSITIVE_INFINITY), 1);
});

test("a press steps by a ratio from what is on screen", () => {
  // Continuous: a pinch settles at 137%, and the next press has to move from
  // there — snapping to the menu's stops sent it *down* to 125%.
  assert.equal(zoomedBy(1.37, 1), 1.713);
  assert.equal(zoomedBy(1.37, -1), 1.096);
  assert.equal(zoomedBy(0.75, 1), 0.938);
  assert.equal(zoomedBy(1, 1), 1.25);
  // Both ends stop rather than wrap.
  assert.equal(zoomedBy(MAX_PDF_ZOOM, 1), MAX_PDF_ZOOM);
  assert.equal(zoomedBy(MIN_PDF_ZOOM, -1), MIN_PDF_ZOOM);
  // A press and its opposite come back to where they started.
  assert.equal(zoomedBy(zoomedBy(1, 1), -1), 1);
  // The menu still offers the named stops for jumping to a known size.
  assert.deepEqual(PDF_ZOOM_OPTIONS, [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4]);
});

test("a step skips the stops the canvas budget has flattened", () => {
  // 612pt page at DPR 2: the budget caps the drawn width at 1722 CSS px, so
  // both 3x (2448 requested) and 4x (3264 requested) land on 211%. Stepping by
  // the requested value alone made 4x->3x a no-op and wasted the first press
  // of a climb; one press must always mean one visible step.
  const page = 612;
  const ratio = 1.414;
  const dpr = 2;
  assert.equal(zoomedPageWidth(page, 3, ratio, dpr), 1722);
  assert.equal(zoomedPageWidth(page, 4, ratio, dpr), 1722);
  // 4x -> smaller skips the collapsed 3x stop and lands where the page shrinks.
  assert.equal(steppedPdfZoomByWidth(4, -1, page, ratio, dpr), 2);
  assert.ok(
    zoomedPageWidth(page, 2, ratio, dpr) < zoomedPageWidth(page, 4, ratio, dpr),
  );
  // From 2x (1632px) the next stop 3x really does grow to 1722, so it is taken.
  assert.equal(steppedPdfZoomByWidth(2, 1, page, ratio, dpr), 3);
  // With no clamping in play the ladder is walked one stop at a time.
  assert.equal(steppedPdfZoomByWidth(1, 1, page, ratio, dpr), 1.25);
  assert.equal(steppedPdfZoomByWidth(2, 1, page, 4, 1), 3);
});

test("a control is enabled only when its step changes the drawn width", () => {
  const page = 612;
  const ratio = 1.414;
  const dpr = 2;
  const landed = zoomedPageWidth(page, 4, ratio, dpr);
  // At the clamped 4x there is no larger width to reach, so zoom-in is spent.
  assert.equal(canStepPdfZoom(1, 4, page, ratio, dpr, landed), false);
  assert.equal(canStepPdfZoom(-1, 4, page, ratio, dpr, landed), true);
  // At the floor, shrinking has nowhere to go.
  const floor = zoomedPageWidth(page, MIN_PDF_ZOOM, ratio, dpr);
  assert.equal(canStepPdfZoom(-1, MIN_PDF_ZOOM, page, ratio, dpr, floor), false);
  // A clamped 3x still has 4x above it? No: both land on the same width, so the
  // honest answer is that another press cannot change anything.
  const threeLanded = zoomedPageWidth(page, 3, ratio, dpr);
  assert.equal(canStepPdfZoom(1, 3, page, ratio, dpr, threeLanded), false);
});

test("100% is the page's real size, not its scale:1 size", () => {
  // PDF points are 1/72", CSS pixels 1/96": a 612pt Letter page is 816px.
  assert.equal(ACTUAL_SIZE_FACTOR, 96 / 72);
  assert.equal(actualSizeWidth(612), 816);
  assert.equal(actualSizeWidth(0), 0);
  assert.equal(effectiveZoomPercent(816, 612), 100);
});

test("fixed width follows the page, and the canvas budget caps it", () => {
  const dpr1 = maxPageWidth(1.414, 1);
  const dpr2 = maxPageWidth(1.414, 2);
  assert.equal(dpr1, 3444);
  assert.equal(dpr2, 1722);
  assert.equal(zoomedPageWidth(600, 1, 1.414, 1), 800);
  assert.equal(zoomedPageWidth(600, 2, 1.414, 1), 1600);
  assert.equal(zoomedPageWidth(600, 4, 1.414, 1), 3200);
  // 4× on a 2× display would exceed the budget, so the width is clamped and
  // the toolbar reports what actually landed rather than 400%.
  assert.equal(zoomedPageWidth(600, 4, 1.414, 2), dpr2);
  assert.equal(
    effectiveZoomPercent(zoomedPageWidth(600, 4, 1.414, 2), 600),
    215,
  );
  // Never narrower than the reader's own floor, whatever the page size.
  assert.equal(zoomedPageWidth(10, 0.25, 1.414, 1), MIN_PAGE_WIDTH);
  assert.equal(MAX_PAGE_CANVAS_PIXELS, 16_777_216);
});

test("fit ratio seeds the first step from what is on screen", () => {
  // A 600pt page (800px at 100%) fitted to 600px is drawn at 75%, so the first
  // press must go to 100%, not to 25%.
  assert.equal(fitZoomRatio(600, 600), 0.75);
  assert.equal(fitZoomRatio(800, 600), 1);
  // A wide page in a narrow pane can fit below the floor; the floor wins so the
  // first press still enlarges what the reader is looking at.
  assert.equal(fitZoomRatio(160, 600), MIN_PDF_ZOOM);
  assert.equal(fitZoomRatio(0, 600), 1);
  assert.equal(fitZoomRatio(600, 0), 1);
});

test("stored zoom is bounded and malformed values fall back", () => {
  assert.deepEqual(normalisePdfZoom(undefined), DEFAULT_PDF_ZOOM);
  assert.deepEqual(normalisePdfZoom({}), DEFAULT_PDF_ZOOM);
  assert.deepEqual(normalisePdfZoom({ mode: "weird" }), DEFAULT_PDF_ZOOM);
  assert.deepEqual(normalisePdfZoom({ mode: "fixed" }), DEFAULT_PDF_ZOOM);
  assert.deepEqual(normalisePdfZoom({ mode: "fixed", scale: 99 }), {
    mode: "fixed",
    scale: MAX_PDF_ZOOM,
  });
  assert.deepEqual(normalisePdfZoom({ mode: "fixed", scale: 0.1 }), {
    mode: "fixed",
    scale: MIN_PDF_ZOOM,
  });
  assert.deepEqual(
    normalisePdfZoom({ mode: "fixed", scale: Number.NaN }),
    DEFAULT_PDF_ZOOM,
  );
});

test("the three page-size modes round-trip, and fitting the text is the default", () => {
  // A reader, not a document inspector: the paper margins exist for binding
  // and thumbs, so the default fills the pane with the text block.
  assert.deepEqual(DEFAULT_PDF_ZOOM, { mode: "text" });
  assert.equal(cropsPageMargins(DEFAULT_PDF_ZOOM), true);
  assert.equal(cropsPageMargins({ mode: "fit" }), false);
  assert.equal(cropsPageMargins({ mode: "fixed", scale: 2 }), false);
  assert.deepEqual(normalisePdfZoom({ mode: "text" }), { mode: "text" });
  assert.deepEqual(normalisePdfZoom({ mode: "fit" }), { mode: "fit" });
});

test("zoom shortcuts are scoped to a hovered or focused reader", () => {
  assert.equal(
    pdfZoomShortcut({
      key: "+",
      modifier: false,
      readerHovered: true,
      readerFocused: true,
    }),
    null,
  );
  assert.equal(
    pdfZoomShortcut({
      key: "+",
      modifier: true,
      readerHovered: false,
      readerFocused: false,
    }),
    null,
  );
  const base = { modifier: true, readerHovered: true, readerFocused: false };
  assert.equal(pdfZoomShortcut({ ...base, key: "+" }), "increase");
  assert.equal(pdfZoomShortcut({ ...base, key: "=" }), "increase");
  assert.equal(pdfZoomShortcut({ ...base, key: "-" }), "decrease");
  assert.equal(pdfZoomShortcut({ ...base, key: "0" }), "reset");
  assert.equal(pdfZoomShortcut({ ...base, key: "z" }), null);
});

test("zoom lives in its own store, not in the text typography preferences", () => {
  // The text preferences carry an exact-shape assertion in their own test;
  // adding a page-bitmap field there would break it and hand the text and EPUB
  // readers a value they cannot honour. Asserting on the STORED KEY (a public
  // contract) rather than on source text keeps this from breaking on any
  // refactor of either module.
  assert.equal(PDF_ZOOM_KEY, "dt.reader.pdfZoom");
  // The preference is a closed union: there is no field to smuggle a page
  // bitmap into, which is the whole point of keeping it out of the typography
  // store.
  const preference: PdfZoomPreference = DEFAULT_PDF_ZOOM;
  assert.deepEqual(preference, { mode: "fit" });
});

test("new copy is translated in every shipped locale", () => {
  // This used to read only `en`, so a locale that never got the key still
  // passed. `web/i18n/init.ts` is the list of shipped locales; read it rather
  // than hard-coding, so a new locale is covered the day it ships.
  const init = readFileSync("i18n/init.ts", "utf8");
  const shipped = [...init.matchAll(/locales\/([a-z]{2})\/app\.json/g)].map(
    (match) => match[1],
  );
  assert.ok(shipped.includes("en"), "en must be a shipped locale");
  for (const key of [
    "Zoom level",
    "Reset zoom",
    "Zoom in",
    "Zoom out",
    "Fit",
  ]) {
    for (const locale of shipped) {
      const body = readFileSync(`locales/${locale}/app.json`, "utf8");
      assert.ok(
        body.includes(`"${key}"`),
        `${locale}/app.json is missing the "${key}" key`,
      );
    }
  }
});
