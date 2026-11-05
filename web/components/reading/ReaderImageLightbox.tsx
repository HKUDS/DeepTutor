"use client";

import { Maximize, X, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { PreferenceButton } from "./ReaderDisplayControls";

const MIN_IMAGE_ZOOM = 1;
const MAX_IMAGE_ZOOM = 6;
const DOUBLE_TAP_ZOOM = 2.5;
const WHEEL_STEP = 0.002;
const BUTTON_STEP = 1.25;

interface ImageView {
  scale: number;
  x: number;
  y: number;
}

const FIT_VIEW: ImageView = { scale: 1, x: 0, y: 0 };

/**
 * Full-screen viewer for a picture from the text or EPUB reader.
 *
 * The reader's own images are capped by the column they sit in — `max-h-[70vh]`
 * in the text view, `max-height: 85vh` injected into the EPUB iframe — so a
 * diagram's labels are unreadable at reading size. This draws the picture at
 * its own size instead and lets the reader zoom and pan it.
 *
 * A portal rather than the shared `Dialog`: that component brings a header, a
 * footer and a `max-w-*` box, none of which suit a picture that should fill the
 * window.
 */
export function ReaderImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [view, setView] = useState<ImageView>(FIT_VIEW);

  const zoomByFactor = useCallback((factor: number) => {
    setView((current) => {
      const scale = Math.min(
        MAX_IMAGE_ZOOM,
        Math.max(MIN_IMAGE_ZOOM, current.scale * factor),
      );
      if (scale === current.scale) return current;
      // Back at fit there is nothing to pan to, so drop the offset with it.
      return scale === MIN_IMAGE_ZOOM ? FIT_VIEW : { ...current, scale };
    });
  }, []);

  const resetView = useCallback(() => setView(FIT_VIEW), []);

  // Focus lands on the dialog and returns where it came from, so a keyboard
  // reader is not dropped at the top of the document on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    backdropRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  // A non-passive wheel listener: React attaches wheel handlers passively, so
  // `preventDefault` there would only log a warning and the document behind the
  // overlay would scroll.
  useEffect(() => {
    const node = backdropRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const unit =
        event.deltaMode === 1
          ? 16
          : event.deltaMode === 2
            ? node.clientHeight
            : 1;
      const delta = Math.max(-40, Math.min(40, event.deltaY * unit));
      zoomByFactor(Math.exp(-delta * WHEEL_STEP));
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [zoomByFactor]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomByFactor(BUTTON_STEP);
      } else if (event.key === "-") {
        event.preventDefault();
        zoomByFactor(1 / BUTTON_STEP);
      } else if (event.key === "0") {
        event.preventDefault();
        resetView();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, resetView, zoomByFactor]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={backdropRef}
      role="dialog"
      aria-modal="true"
      aria-label={t("Image")}
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-[2px]"
    >
      <div
        className="relative flex max-h-full max-w-full items-center justify-center p-6"
        // Clipping keeps a zoomed picture inside the dialog instead of letting
        // it push a scrollbar onto the page behind.
        style={{ overflow: "hidden", touchAction: "none" }}
        onPointerDown={(event) => {
          if (view.scale <= MIN_IMAGE_ZOOM) return;
          dragRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            originX: view.x,
            originY: view.y,
          };
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          const x = drag.originX + event.clientX - drag.startX;
          const y = drag.originY + event.clientY - drag.startY;
          setView((current) => ({ ...current, x, y }));
        }}
        onPointerUp={() => {
          dragRef.current = null;
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
        onDoubleClick={() => {
          setView((current) =>
            current.scale > MIN_IMAGE_ZOOM
              ? FIT_VIEW
              : { scale: DOUBLE_TAP_ZOOM, x: 0, y: 0 },
          );
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- the picture comes from the material, not the app's asset pipeline. */}
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="select-none object-contain shadow-[0_20px_60px_rgba(0,0,0,0.45)]"
          style={{
            // Fit the window at 1×, then scale by transform: a `max-w-full`
            // would keep overriding the size and the picture could never grow.
            maxWidth: "92vw",
            maxHeight: "88vh",
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
        />
      </div>

      <div className="absolute inset-x-0 bottom-4 flex justify-center">
        <div
          role="toolbar"
          aria-label={t("Zoom level")}
          className="flex items-center gap-0.5 rounded-xl bg-white/10 px-1.5 py-1 text-white backdrop-blur"
        >
          <PreferenceButton
            label={t("Zoom out")}
            icon={ZoomOut}
            disabled={view.scale <= MIN_IMAGE_ZOOM}
            onClick={() => zoomByFactor(1 / BUTTON_STEP)}
          />
          <span className="min-w-[52px] text-center text-[12px] tabular-nums">
            {`${Math.round(view.scale * 100)}%`}
          </span>
          <PreferenceButton
            label={t("Zoom in")}
            icon={ZoomIn}
            disabled={view.scale >= MAX_IMAGE_ZOOM}
            onClick={() => zoomByFactor(BUTTON_STEP)}
          />
          <PreferenceButton
            label={t("Fit")}
            icon={Maximize}
            onClick={resetView}
          />
          <PreferenceButton label={t("Close")} icon={X} onClick={onClose} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
