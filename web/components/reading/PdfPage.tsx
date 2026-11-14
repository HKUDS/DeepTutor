"use client";

import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
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
}

/** Debounce before the single final repaint once a resize settles. */
const FINAL_REPAINT_DELAY_MS = 150;
/** Set on the text layer root by React rather than pdf.js. */
const REACT_OWNED_TEXT_STYLES = new Set(["--total-scale-factor", "pointer-events"]);

function copyPdfjsRootMetadata(source: HTMLElement, target: HTMLElement) {
  for (let index = 0; index < source.style.length; index += 1) {
    const name = source.style.item(index);
    if (!name || REACT_OWNED_TEXT_STYLES.has(name)) continue;
    target.style.setProperty(
      name,
      source.style.getPropertyValue(name),
      source.style.getPropertyPriority(name),
    );
  }
  for (const attribute of source.attributes) {
    if (!attribute.name.startsWith("data-")) continue;
    target.setAttribute(attribute.name, attribute.value);
  }
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
}: PdfPageProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  // Whether this page was ever drawn, so only those are handed back.
  const renderedRef = useRef(false);
  const paintedWidthRef = useRef<number | null>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  const [baseWidth, setBaseWidth] = useState(0);
  const [canvasFailed, setCanvasFailed] = useState(false);
  const [textFailed, setTextFailed] = useState(false);

  const height = Math.round(width * (ratio ?? fallbackRatio));
  const textScale = baseWidth > 0 ? width / baseWidth : 1;

  useEffect(() => {
    if (!active || width <= 0) return;
    let cancelled = false;
    let renderTask: { cancel: () => void } | null = null;
    let cancelSchedule: (() => void) | null = null;

    (async () => {
      try {
        const page = await doc.getPage(locator);
        renderedRef.current = true;
        if (cancelled) return;
        const base = page.getViewport({ scale: 1 });
        if (base.width > 0) {
          setRatio(base.height / base.width);
          setBaseWidth(base.width);
        }

        const paintCanvas = async () => {
          const canvas = canvasRef.current;
          if (!canvas) return;
          const dpr = outputScale();
          try {
            const base = page.getViewport({ scale: 1 });
            const viewport = page.getViewport({ scale: width / base.width });
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
            if (cancelled) return;
            paintedWidthRef.current = width;
            setCanvasFailed(false);
          } catch (error) {
            // pdf.js throws RenderingCancelledException on a cancelled task —
            // that is the normal path when scrolling, not a failure to report.
            const name = (error as { name?: string } | null)?.name ?? "";
            if (!cancelled && name !== "RenderingCancelledException") {
              setCanvasFailed(true);
            }
          }
        };

        if (paintedWidthRef.current == null) {
          void paintCanvas();
        } else if (paintedWidthRef.current !== width) {
          // Resize: keep the CSS-scaled bitmap until the width settles, then
          // repaint once at the final size.
          const handle = window.setTimeout(
            () => void paintCanvas(),
            FINAL_REPAINT_DELAY_MS,
          );
          cancelSchedule = () => window.clearTimeout(handle);
        }
      } catch (error) {
        // pdf.js throws RenderingCancelledException on a cancelled task — that
        // is the normal path when scrolling, not a failure to report.
        const name = (error as { name?: string } | null)?.name ?? "";
        if (!cancelled && name !== "RenderingCancelledException") {
          setCanvasFailed(true);
          setTextFailed(true);
        }
      }
    })();

    return () => {
      cancelled = true;
      cancelSchedule?.();
      try {
        renderTask?.cancel();
      } catch {
        // Already settled.
      }
    };
  }, [active, doc, locator, width]);

  // Build the text layer once per active period, independently of bitmap
  // completion. Resizing changes only --total-scale-factor.
  useEffect(() => {
    const container = textLayerRef.current;
    if (!active || !container) return;

    let cancelled = false;
    let textLayer: { cancel: () => void } | null = null;
    container.replaceChildren();
    const buildTextLayer = async () => {
      try {
        const [pdfjs, page] = await Promise.all([loadPdfjs(), doc.getPage(locator)]);
        renderedRef.current = true;
        if (cancelled) return;
        const textContent = await page.getTextContent();
        if (cancelled) return;

        const staged = document.createElement("div");
        staged.className = "textLayer";
        staged.style.setProperty("--total-scale-factor", "1");
        const layer = new pdfjs.TextLayer({
          textContentSource: textContent,
          container: staged,
          viewport: page.getViewport({ scale: 1 }),
        });
        textLayer = layer;
        await layer.render();
        if (cancelled) return;

        copyPdfjsRootMetadata(staged, container);
        container.replaceChildren(...staged.childNodes);
        setTextFailed(false);
      } catch (error) {
        const name = (error as { name?: string } | null)?.name ?? "";
        if (!cancelled && name !== "AbortException") setTextFailed(true);
      }
    };

    void buildTextLayer();

    return () => {
      cancelled = true;
      try {
        textLayer?.cancel();
      } catch {
        // Already settled.
      }
    };
  }, [active, doc, locator]);

  // Free the canvas bitmap when the page scrolls far away. Without this a
  // 600-page document accumulates every page it ever showed.
  useEffect(() => {
    if (active) return;
    paintedWidthRef.current = null;
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
    // Only pages that were drawn: asking for the rest would load them.
    if (retain || !renderedRef.current) return;
    releasePage(doc, locator);
  }, [retain, doc, locator]);

  useEffect(
    () => () => {
      paintedWidthRef.current = null;
      if (renderedRef.current) releasePage(doc, locator);
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
      className="relative mx-auto shrink-0 overflow-hidden rounded-[10px] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.10),0_8px_24px_-12px_rgba(0,0,0,0.18)] ring-1 ring-black/[0.06]"
      style={{ width, height }}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
      <div
        ref={textLayerRef}
        className="textLayer"
        // The text layer is the selection surface; annotations sit above it but
        // must not swallow drags, so only this layer takes pointer events.
        style={
          {
            pointerEvents: "auto",
            "--total-scale-factor": String(textScale),
          } as CSSProperties
        }
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
      {canvasFailed && textFailed && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/90 px-6 text-center">
          <span className="text-[12px] text-[var(--muted-foreground)]">
            {t("This page could not be rendered.")}
          </span>
        </div>
      )}
    </div>
  );
}
