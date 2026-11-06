"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";
import { loadPdfjs, outputScale, type PdfDocument } from "@/lib/pdfjs-loader";
import type { NormalisedBox } from "@/lib/pdf-page-geometry";
import { MAX_PAGE_CANVAS_PIXELS } from "@/lib/reading-zoom";
import Tooltip from "@/shared/ui/Tooltip";

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;

/**
 * Longest side the preview bitmap may take, in device pixels.
 *
 * A canvas is not useful past a few thousand device pixels on one side: the
 * preview is shown at the pane's width and magnified with a CSS transform, so
 * 8192 device pixels is already more than twice the widest stage at DPR 2
 * (1600 CSS px × 2). It is also the texture size some older mobile GPUs cap at,
 * and far below the 16384 per side current browsers allow.
 *
 * Without a cap, a 2%-wide full-height picture — a legal hotspot, since it
 * passes the 0.3% area threshold — asks for a bitmap a hundred thousand pixels
 * tall on the vertical axis alone.
 */
export const MAX_PREVIEW_CANVAS_AXIS = 8192;

export interface PreviewCanvasPlan {
  /** Scale to render the page at. */
  scale: number;
  /** CSS size of the canvas on the stage. */
  cssWidth: number;
  cssHeight: number;
  /** Device-pixel size of the bitmap. */
  width: number;
  height: number;
}

/**
 * Sizes the preview bitmap for one picture rectangle.
 *
 * `requestedScale` is what the picture would like: enough to make its width
 * fill the stage. A tall narrow rectangle makes that scale enormous, so the
 * scale — never the rectangle — is reduced until the bitmap fits both the page
 * reader's device-pixel budget and {@link MAX_PREVIEW_CANVAS_AXIS}.
 *
 * Shrinking the scale shrinks the CSS box with the bitmap, which keeps the
 * picture sharp at 1:1 and at its natural aspect: the preview is smaller, not
 * a stretched thumbnail, and the reader can still zoom and pan it.
 */
export function previewCanvasPlan(
  regionWidth: number,
  regionHeight: number,
  requestedScale: number,
  dpr: number,
): PreviewCanvasPlan {
  const width = Math.max(1, regionWidth);
  const height = Math.max(1, regionHeight);
  const ratio = Number.isFinite(dpr) && dpr > 0 ? dpr : 1;
  const requested =
    Number.isFinite(requestedScale) && requestedScale > 0 ? requestedScale : 1;
  const deviceWidth = width * requested * ratio;
  const deviceHeight = height * requested * ratio;

  let fit = 1;
  const area = deviceWidth * deviceHeight;
  if (area > MAX_PAGE_CANVAS_PIXELS) {
    fit = Math.sqrt(MAX_PAGE_CANVAS_PIXELS / area);
  }
  const longest = Math.max(deviceWidth, deviceHeight);
  if (longest * fit > MAX_PREVIEW_CANVAS_AXIS) {
    fit = MAX_PREVIEW_CANVAS_AXIS / longest;
  }

  const scale = requested * fit;
  // Floor the CSS box first and derive the bitmap from it: the canvas can only
  // end up smaller than the fitted size, never a rounding step past the caps.
  const cssWidth = Math.max(1, Math.floor(width * scale));
  const cssHeight = Math.max(1, Math.floor(height * scale));
  return {
    scale,
    cssWidth,
    cssHeight,
    width: Math.max(1, Math.floor(cssWidth * ratio)),
    height: Math.max(1, Math.floor(cssHeight * ratio)),
  };
}

export interface PdfImageZoomOverlayProps {
  doc: PdfDocument;
  locator: number;
  /** Picture rectangle in page-normalised coordinates. */
  box: NormalisedBox;
  onClose: () => void;
}

/**
 * Full-screen preview of one picture.
 *
 * Only the picture's rectangle is rendered — at a scale high enough that the
 * canvas is sharp before the reader zooms in further — so opening a thumbnail
 * on a 600-page scan costs one small render rather than a whole-page bitmap.
 * Further magnification is a CSS transform: the bitmap already holds more
 * pixels than the enlarged view asks for.
 */
export function PdfImageZoomOverlay({
  doc,
  locator,
  box,
  onClose,
}: PdfImageZoomOverlayProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointer: number;
    x: number;
    y: number;
    panX: number;
    panY: number;
  } | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  useEffect(() => {
    let cancelled = false;
    let renderTask: { cancel: () => void } | null = null;

    (async () => {
      const page = await doc.getPage(locator);
      if (cancelled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const base = page.getViewport({ scale: 1 });
      const regionWidth = Math.max(1, (box.x1 - box.x0) * base.width);
      const regionHeight = Math.max(1, (box.y1 - box.y0) * base.height);
      const target = Math.min(
        1600,
        Math.max(480, window.innerWidth * 0.82),
      );
      // Rendered at least 1.5× so a narrow picture still looks like a preview
      // rather than a stretched thumbnail. `previewCanvasPlan` then reduces the
      // scale when that request would ask for a bitmap past the page reader's
      // budget or past the single-axis cap — a legal 2%-wide full-height
      // hotspot would otherwise allocate hundreds of MiB.
      const requestedScale = Math.max(1.5, target / regionWidth);
      const dpr = outputScale();
      const plan = previewCanvasPlan(
        regionWidth,
        regionHeight,
        requestedScale,
        dpr,
      );
      canvas.width = plan.width;
      canvas.height = plan.height;
      canvas.style.width = `${plan.cssWidth}px`;
      canvas.style.height = `${plan.cssHeight}px`;
      const viewport = page.getViewport({ scale: plan.scale });
      const shiftX = -box.x0 * base.width * plan.scale * dpr;
      const shiftY = -box.y0 * base.height * plan.scale * dpr;
      renderTask = page.render({
        canvas,
        viewport,
        transform: [dpr, 0, 0, dpr, shiftX, shiftY],
      });
      await (renderTask as unknown as { promise: Promise<void> }).promise;
      if (!cancelled) setStatus("ready");
    })().catch(() => {
      if (!cancelled) setStatus("error");
    });

    return () => {
      cancelled = true;
      try {
        renderTask?.cancel();
      } catch {
        // Already settled.
      }
    };
  }, [doc, locator, box.x0, box.y0, box.x1, box.y1]);

  // Wheel zoom needs a non-passive listener: React attaches wheel handlers
  // passively, so `preventDefault` there would only log a warning and the page
  // behind the overlay would scroll.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      setZoom((current) =>
        Math.min(
          MAX_ZOOM,
          Math.max(MIN_ZOOM, current * Math.exp(-event.deltaY * 0.0015)),
        ),
      );
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("Image preview")}
      className="fixed inset-0 z-50 flex flex-col bg-black/85"
      onClick={onClose}
    >
      <div
        className="flex shrink-0 items-center justify-end gap-1 px-3 py-2 text-white/90"
        onClick={(event) => event.stopPropagation()}
      >
        <span className="mr-auto text-[12px] tabular-nums text-white/60">
          {t("Page {{n}}", { n: locator })}
          <span className="ml-2 text-white/40">
            {t("Drag to pan, scroll to zoom")}
          </span>
        </span>
        <Tooltip label={t("Zoom out")}>
          <button
            type="button"
            aria-label={t("Zoom out")}
            onClick={() =>
              setZoom((current) => Math.max(MIN_ZOOM, current / 1.3))
            }
            className="inline-flex size-7 items-center justify-center rounded-lg transition hover:bg-white/15"
          >
            <ZoomOut size={15} />
          </button>
        </Tooltip>
        <Tooltip label={t("Zoom in")}>
          <button
            type="button"
            aria-label={t("Zoom in")}
            onClick={() =>
              setZoom((current) => Math.min(MAX_ZOOM, current * 1.3))
            }
            className="inline-flex size-7 items-center justify-center rounded-lg transition hover:bg-white/15"
          >
            <ZoomIn size={15} />
          </button>
        </Tooltip>
        <Tooltip label={t("Reset zoom")}>
          <button
            type="button"
            aria-label={t("Reset zoom")}
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="inline-flex size-7 items-center justify-center rounded-lg transition hover:bg-white/15"
          >
            <RotateCcw size={15} />
          </button>
        </Tooltip>
        <Tooltip label={t("Close")}>
          <button
            type="button"
            aria-label={t("Close")}
            onClick={onClose}
            className="inline-flex size-7 items-center justify-center rounded-lg transition hover:bg-white/15"
          >
            <X size={15} />
          </button>
        </Tooltip>
      </div>

      <div
        ref={stageRef}
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-4 pb-4"
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => {
          dragRef.current = {
            pointer: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            panX: pan.x,
            panY: pan.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointer !== event.pointerId) return;
          setPan({
            x: drag.panX + event.clientX - drag.x,
            y: drag.panY + event.clientY - drag.y,
          });
        }}
        onPointerUp={(event) => {
          if (dragRef.current?.pointer !== event.pointerId) return;
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        style={{ cursor: zoom > 1 ? "grab" : "default", touchAction: "none" }}
      >
        {status === "loading" && (
          <span className="flex items-center gap-2 text-[12px] text-white/60">
            <Loader2 size={14} className="animate-spin" />
            {t("Loading image…")}
          </span>
        )}
        {status === "error" && (
          <span className="text-[12px] text-white/60">
            {t("This image could not be rendered.")}
          </span>
        )}
        <canvas
          ref={canvasRef}
          className="rounded-[6px] bg-white shadow-2xl"
          style={{
            display: status === "ready" ? "block" : "none",
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        />
      </div>
    </div>
  );
}
