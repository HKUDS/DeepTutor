"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { loadPdfjs, outputScale, type PdfDocument } from "@/lib/pdfjs-loader";
import type { AnnotationItem } from "@/lib/reading-api";
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
  annotations: AnnotationItem[];
  highlightedAnnotationId?: string | null;
  /** Transient highlight from `reader_goto`, as normalised rects. */
  flashRects?: Array<[number, number, number, number]>;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
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
export function PdfPage({
  doc,
  locator,
  width,
  fallbackRatio,
  active,
  annotations,
  highlightedAnnotationId,
  flashRects,
  onAnnotationClick,
}: PdfPageProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

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
        if (cancelled) return;

        const base = page.getViewport({ scale: 1 });
        if (base.width > 0) {
          setRatio(base.height / base.width);
        }
        const scale = width / base.width;
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
          const dpr = outputScale();
          canvas.width = Math.floor(viewport.width * dpr);
          canvas.height = Math.floor(viewport.height * dpr);
          canvas.style.width = `${Math.floor(viewport.width)}px`;
          canvas.style.height = `${Math.floor(viewport.height)}px`;
          // `canvas` only, never alongside `canvasContext`: pdf.js documents the
          // context parameter as backwards-compatibility requiring
          // `canvas: null`, and passing both is an unsupported combination.
          renderTask = page.render({
            canvas,
            viewport,
            transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
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
  }, [doc, locator, width, active]);

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

  const pageAnnotations = useMemo(
    () => annotations.filter((a) => a.locator === locator),
    [annotations, locator],
  );

  return (
    <div
      data-reader-unit={locator}
      className="relative mx-auto shrink-0 overflow-hidden rounded-[10px] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.10),0_8px_24px_-12px_rgba(0,0,0,0.18)] ring-1 ring-black/[0.06]"
      style={{ width, height }}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
      <div
        ref={textLayerRef}
        className="textLayer"
        // The text layer is the selection surface; annotations sit above it but
        // must not swallow drags, so only this layer takes pointer events.
        style={{ pointerEvents: "auto" }}
      />
      <AnnotationLayer
        annotations={pageAnnotations}
        highlightedAnnotationId={highlightedAnnotationId}
        flashRects={flashRects}
        onAnnotationClick={onAnnotationClick}
      />
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
