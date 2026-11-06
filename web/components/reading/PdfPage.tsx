"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { loadPdfjs, outputScale, type PdfDocument } from "@/lib/pdfjs-loader";
import type { AnnotationItem } from "@/lib/reading-api";
import {
  cropLayout,
  measurePageInkBox,
  type NormalisedBox,
} from "@/lib/pdf-page-geometry";
import { canvasPixelRatio } from "@/lib/reading-zoom";
import { AnnotationLayer } from "./AnnotationLayer";

export interface PdfPageProps {
  doc: PdfDocument;
  locator: number;
  /** CSS width the page should occupy; height follows the page's aspect ratio. */
  width: number;
  /** Placeholder aspect ratio (height / width) until the real page is measured. */
  fallbackRatio: number;
  /** False while the page is far outside the viewport — keeps memory bounded. */
  active: boolean;
  /**
   * Keep pdf.js's parsed copy of the page while it is near, even off-canvas:
   * scrolling back a page or two then repaints instead of parsing again.
   * Further away it is handed back. Defaults to ``active``.
   */
  retain?: boolean;
  annotations: AnnotationItem[];
  highlightedAnnotationId?: string | null;
  /** Transient highlight from `reader_goto`, as normalised rects. */
  flashRects?: Array<[number, number, number, number]>;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  /** Trim the page's own white side margins so the text block fills the pane. */
  cropMargins?: boolean;
  /**
   * Reports this page's share of the page its visible strip covers, so the
   * reader can measure "one zoom stop" from the size actually on screen. The
   * locator tags the report: several pages are mounted at once, and a
   * neighbour's ratio must never stand in for the page being read.
   */
  onCropRatio?: (locator: number, ratio: number) => void;
  /**
   * Cache key for the ink and picture measurements: a page that changes
   * material must never show the previous one's crop.
   */
  inkKey?: string;
}

/**
 * One rendered PDF page: canvas, selectable text layer, annotation overlay.
 *
 * Rendering is gated on `active` and every effect cancels its in-flight work,
 * because scrolling a long document mounts and unmounts pages faster than
 * pdf.js can finish: without cancellation the canvas of a page that scrolled
 * away keeps decoding, and a late `render` can paint over a newer one.
 *
 * The page keeps its measured height while inactive, so deactivating it does not
 * collapse the scroll container and yank the reader's position.
 */
/** Let pdf.js drop a page's decoded images and operator list. */
function releasePage(doc: PdfDocument, locator: number) {
  void doc.getPage(locator).then((page) => page.cleanup()).catch(() => undefined);
}

export function PdfPage({
  doc,
  locator,
  width,
  fallbackRatio,
  active,
  retain = active,
  annotations,
  highlightedAnnotationId,
  flashRects,
  onAnnotationClick,
  cropMargins = false,
  onCropRatio,
  inkKey = `${doc ? "doc" : "none"}:${locator}`,
}: PdfPageProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  // Whether this page was ever drawn, so only those are handed back.
  const renderedRef = useRef(false);
  // Whether this page's ink was ever measured. Measuring parses the page, so a
  // page measured but never painted holds pdf.js's decoded copy just like a
  // rendered one and has to be handed back too.
  const measuredRef = useRef(false);
  const [ratio, setRatio] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  // `undefined` means "not measured yet"; `null` means "measured, nothing to
  // crop". Painting waits for the answer so a page is not drawn once at full
  // width and again at the cropped one.
  const [inkState, setInkState] = useState<{
    key: string;
    box: NormalisedBox | null;
  } | null>(null);
  const inkBox = !cropMargins
    ? null
    : inkState?.key === inkKey
      ? inkState.box
      : undefined;

  const layout = useMemo(
    () =>
      cropLayout(
        width,
        ratio ?? fallbackRatio,
        cropMargins ? (inkBox ?? null) : null,
      ),
    [width, ratio, fallbackRatio, cropMargins, inkBox],
  );

  // How much of the page this strip shows. Reported only while this page is
  // active: every page measures its own margins, and the zoom step must start
  // from what is under the reader's eyes.
  //
  // Reported in every mode, not only while cropping: a page drawn whole is
  // showing all of itself, so the share is 1. Leaving the last text-mode ratio
  // behind made one press of "+" after switching to Fit page divide the fit
  // ratio by a crop that is no longer on screen — 1250px instead of 750px.
  //
  // The locator goes with it because the render window holds neighbours too:
  // an untagged report let whichever page settled last define the step.
  useEffect(() => {
    if (!active || !onCropRatio) return;
    onCropRatio(locator, layout.visibleWidth / layout.fullWidth);
  }, [active, locator, layout.visibleWidth, layout.fullWidth, onCropRatio]);

  // -- ink box -------------------------------------------------------------

  // Measured only inside the render window. `PdfDocumentView` mounts a page for
  // every locator, so measuring on mount would start a scratch render for a
  // 600-page document as soon as it opened with Fit text — the expensive work
  // belongs to the pages that can be seen, or are about to be.
  const shouldMeasureInk = cropMargins && (active || retain);

  useEffect(() => {
    if (!shouldMeasureInk) return;
    let cancelled = false;
    // Marked before the await: the page is parsed for its ink as soon as
    // `getPage` is called, and the cleanup below has to hand back one that was
    // measured but never painted.
    measuredRef.current = true;
    (async () => {
      const page = await doc.getPage(locator);
      if (cancelled) return;
      const box = await measurePageInkBox(page, inkKey);
      if (!cancelled) setInkState({ key: inkKey, box });
    })().catch(() => {
      if (!cancelled) setInkState({ key: inkKey, box: null });
    });
    return () => {
      cancelled = true;
    };
  }, [doc, locator, inkKey, shouldMeasureInk]);

  // -- pictures ------------------------------------------------------------


  const height = Math.round(width * (ratio ?? fallbackRatio));

  useEffect(() => {
    if (!active || width <= 0) return;
    let cancelled = false;
    let renderTask: { cancel: () => void } | null = null;
    let textLayer: { cancel: () => void } | null = null;

    (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const page = await doc.getPage(locator);
        renderedRef.current = true;
        if (cancelled) return;

        const base = page.getViewport({ scale: 1 });
        if (base.width > 0) {
          setRatio(base.height / base.width);
        }
        // The layout decides how much of the page is visible; the scale is
        // still the full page's, because the bitmap is a window onto it.
        const scale = layout.fullWidth / base.width;
        const viewport = page.getViewport({ scale });

        // Canvas and text layer are rendered CONCURRENTLY and independently.
        // The text layer needs only the viewport and the page's text content —
        // it has no dependency on the bitmap being finished — so chaining it
        // behind the canvas render promise only made selection and quote
        // highlighting hostage to that promise settling. Some embedded browsers
        // paint the page but never settle it, which produced a document that
        // looked perfect and could not be selected at all.
        const paintCanvas = async () => {
          const canvas = canvasRef.current;
          if (!canvas) return;
          // The bitmap holds only the visible strip, and the page is drawn
          // shifted left by the cropped margin. Clamp this page's own bitmap
          // against the budget: the caller clamps the *shared* width using page
          // one's aspect, so a page whose own ratio is taller can still ask for
          // a bitmap past the budget — which the browser drops as a blank page
          // rather than an error. The ratio gives, the CSS box does not, so the
          // layout width stays identical from page to page.
          const dpr = canvasPixelRatio(
            layout.visibleWidth,
            layout.fullHeight,
            outputScale(),
          );
          canvas.width = Math.max(1, Math.floor(layout.visibleWidth * dpr));
          canvas.height = Math.max(1, Math.floor(layout.fullHeight * dpr));
          canvas.style.width = `${layout.visibleWidth}px`;
          canvas.style.height = `${layout.fullHeight}px`;
          const shiftX = -layout.offsetX * dpr;
          // `canvas` only, never alongside `canvasContext`: pdf.js documents the
          // context parameter as backwards-compatibility requiring
          // `canvas: null`, and passing both is an unsupported combination.
          renderTask = page.render({
            canvas,
            viewport,
            transform:
              dpr !== 1 || layout.offsetX
                ? [dpr, 0, 0, dpr, shiftX, 0]
                : undefined,
          });
          await (renderTask as unknown as { promise: Promise<void> }).promise;
        };

        const buildTextLayer = async () => {
          const textContent = await page.getTextContent();
          // Re-checked after the await: two runs of this effect (a resize
          // mid-render) would otherwise both reach `render()` on the same
          // container and the loser would wipe the winner's spans.
          if (cancelled) return;
          const container = textLayerRef.current;
          if (!container) return;
          container.replaceChildren();
          // pdf.js positions the spans with `--total-scale-factor`; without it
          // every run collapses to the same tiny size and selection is useless.
          container.style.setProperty("--total-scale-factor", String(scale));
          const layer = new pdfjs.TextLayer({
            textContentSource: textContent,
            container,
            viewport,
          });
          textLayer = layer as unknown as { cancel: () => void };
          await layer.render();
        };

        // allSettled: a canvas failure must not cost the page its text layer,
        // and vice versa. Failures are reported below only if BOTH sides failed,
        // since either one alone still leaves a usable page.
        const outcomes = await Promise.allSettled([
          paintCanvas(),
          buildTextLayer(),
        ]);
        if (cancelled) return;
        const fatal = outcomes.every(
          (outcome) =>
            outcome.status === "rejected" &&
            (outcome.reason as { name?: string } | null)?.name !==
              "RenderingCancelledException",
        );
        setFailed(fatal);
      } catch (error) {
        // pdf.js throws RenderingCancelledException on a cancelled task — that
        // is the normal path when scrolling, not a failure to report.
        const name = (error as { name?: string } | null)?.name ?? "";
        if (!cancelled && name !== "RenderingCancelledException") {
          setFailed(true);
        }
      }
    })();

    return () => {
      cancelled = true;
      try {
        renderTask?.cancel();
      } catch {
        // Already settled.
      }
      try {
        textLayer?.cancel();
      } catch {
        // Already settled.
      }
    };
  }, [doc, locator, width, active, layout]);

  // Free the canvas bitmap when the page scrolls far away. Without this a
  // 600-page document accumulates every page it ever showed.
  useEffect(() => {
    if (active) return;
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = 0;
      canvas.height = 0;
    }
    textLayerRef.current?.replaceChildren();
  }, [active]);

  // The bitmap is only half of it: pdf.js keeps each page's decoded images
  // and operator list until told to let go — tens of MB a page for a scan.
  useEffect(() => {
    // `cleanup` waits for a cancelled render to settle before it frees.
    // Only pages that were drawn or measured: asking for the rest would load
    // them.
    if (retain || !(renderedRef.current || measuredRef.current)) return;
    releasePage(doc, locator);
  }, [retain, doc, locator]);

  useEffect(
    () => () => {
      if (renderedRef.current || measuredRef.current) releasePage(doc, locator);
    },
    [doc, locator],
  );

  const pageAnnotations = useMemo(
    () => annotations.filter((a) => a.locator === locator),
    [annotations, locator],
  );

  return (
    <div
      data-reader-unit={locator}
      data-page-width={layout.fullWidth}
      data-page-offset-x={layout.offsetX}
      className="relative mx-auto shrink-0 overflow-hidden rounded-[10px] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.10),0_8px_24px_-12px_rgba(0,0,0,0.18)] ring-1 ring-black/[0.06]"
      style={{ width: layout.visibleWidth, height: layout.fullHeight }}
    >
      {/* Whole-page coordinates live here; the clip above trims the margins. */}
      <div
        className="absolute top-0"
        // Explicit height: every child is absolutely positioned, so without it
        // this surface would collapse and the annotation overlay (inset-0) with
        // it.
        style={{
          left: -layout.offsetX,
          top: 0,
          width: layout.fullWidth,
          height: layout.fullHeight,
        }}
      >
      <canvas
        ref={canvasRef}
        className="absolute block"
        // The bitmap holds the visible strip only, so it starts where that
        // strip starts inside the page.
        style={{
          left: layout.offsetX,
          top: 0,
          width: layout.visibleWidth,
          height: layout.fullHeight,
        }}
      />
      <div
        ref={textLayerRef}
        className="textLayer absolute left-0 top-0"
        // The text layer is the selection surface; annotations sit above it but
        // must not swallow drags, so only this layer takes pointer events.
        style={{
          width: layout.fullWidth,
          height: layout.fullHeight,
          pointerEvents: "auto",
        }}
      />
      <AnnotationLayer
        annotations={pageAnnotations}
        highlightedAnnotationId={highlightedAnnotationId}
        flashRects={flashRects}
        onAnnotationClick={onAnnotationClick}
      />
      </div>
      {!active && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="font-mono text-[11px] text-black/25">{locator}</span>
        </div>
      )}
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/90 px-6 text-center">
          <span className="text-[12px] text-[var(--muted-foreground)]">
            {t("This page could not be rendered.")}
          </span>
        </div>
      )}
    </div>
  );
}
