"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";
import { loadPdfjs, outputScale, type PdfDocument } from "@/lib/pdfjs-loader";
import type { NormalisedBox } from "@/lib/pdf-page-geometry";
import Tooltip from "@/shared/ui/Tooltip";

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;

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
      // rather than a stretched thumbnail.
      const scale = Math.max(1.5, target / regionWidth);
      const dpr = outputScale();
      const cssWidth = regionWidth * scale;
      const cssHeight = regionHeight * scale;
      canvas.width = Math.max(1, Math.floor(cssWidth * dpr));
      canvas.height = Math.max(1, Math.floor(cssHeight * dpr));
      canvas.style.width = `${Math.floor(cssWidth)}px`;
      canvas.style.height = `${Math.floor(cssHeight)}px`;
      const viewport = page.getViewport({ scale });
      const shiftX = -box.x0 * base.width * scale * dpr;
      const shiftY = -box.y0 * base.height * scale * dpr;
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
