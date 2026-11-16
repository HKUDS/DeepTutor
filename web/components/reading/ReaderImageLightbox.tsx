"use client";

import { ChevronLeft, ChevronRight, Maximize, X, ZoomIn, ZoomOut } from "lucide-react";

import type { LightboxImage } from "@/lib/reading-images";

// Re-exported so the readers keep importing the type from the component they
// already import the component from.
export type { LightboxImage };
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

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/** The controls a Tab press may land on, in DOM order. */
function focusableControls(root: HTMLElement): HTMLElement[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((node) => node.tabIndex >= 0);
}

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
  images,
  index,
  onIndexChange,
  onClose,
}: {
  /**
   * Every picture the reader can step through, in reading order.
   *
   * The viewer used to take one `src`. Arrow-key navigation was not possible
   * without the list, and the reader does render several pictures per unit —
   * extracted media, inline markers and Markdown images — so the list is what
   * the caller already has in its DOM.
   */
  images: readonly LightboxImage[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}) {
  const current = images[index] ?? images[0];
  const hasNeighbours = images.length > 1;
  const atFirst = index <= 0;
  const atLast = index >= images.length - 1;
  const { t } = useTranslation();
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    captured: boolean;
  } | null>(null);
  // A drag releases over the stage and the browser then reports a click there.
  // That click ended a pan, not a request to dismiss the view being panned.
  const dragMovedRef = useRef(false);
  // What the gesture started on: `true` for the empty stage, `false` for the
  // picture (or anything inside it), `null` when no pointerdown was seen (a
  // keyboard activation, or a test that only dispatches the click).
  //
  // Needed because pointer capture makes the browser retarget pointerup and
  // click to the capturing stage: a tap on the picture then arrives here with
  // `event.target === event.currentTarget`, looking exactly like a click on
  // empty space. Capture is deferred until a pan actually starts, but a
  // gesture that began on the picture must never dismiss the viewer even if a
  // browser reports the click on the stage.
  const pressOnStageRef = useRef<boolean | null>(null);
  const [view, setView] = useState<ImageView>(FIT_VIEW);

  /**
   * Pull focus back when the control that had it becomes disabled.
   *
   * A browser blurs a focused button the moment it turns `disabled` and leaves
   * focus on `<body>`. The viewer's keydown listener is on `window` in the
   * bubble phase, so it still sees the arrows — but the EPUB reader's page-turn
   * guard asks `allowsEpubPageTurn(event.target)`, and `body` is not interactive,
   * so the chapter turned behind an open overlay. Stepping to the last picture
   * disables "next" exactly like that.
   */
  useEffect(() => {
    const root = backdropRef.current;
    if (!root) return;
    const active = document.activeElement;
    if (active && active !== root && root.contains(active)) return;
    if (active && active !== document.body) return;
    root.focus({ preventScroll: true });
  }, [index, images.length, view.scale]);

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

  /**
   * Show the picture at `next`, or do nothing at the ends.
   *
   * The zoom and pan are dropped on every step. They belong to the picture that
   * was on screen, not to the viewer: carrying a 6x zoom and its offset across
   * to the next picture would show it cropped and off-centre, which reads as a
   * broken image rather than a different one.
   */
  const stepTo = useCallback(
    (next: number) => {
      if (next < 0 || next >= images.length || next === index) return;
      setView(FIT_VIEW);
      onIndexChange(next);
    },
    [images.length, index, onIndexChange],
  );

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
      if (event.key === "Tab") {
        // `aria-modal` only tells assistive technology that the rest of the
        // page is inert; the browser still tabs through it. Cycle the dialog's
        // own controls instead, and pull focus back in if it ever got out.
        const root = backdropRef.current;
        if (!root) return;
        const controls = focusableControls(root);
        if (controls.length === 0) {
          event.preventDefault();
          root.focus();
          return;
        }
        const first = controls[0];
        const last = controls[controls.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (!active || !root.contains(active)) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
          return;
        }
        if (event.shiftKey && (active === first || active === root)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }
      // Arrows move between pictures. They are checked before the zoom keys and
      // never while a modifier is held, so a browser shortcut still wins.
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        // Claimed even when there is nowhere to step: with the viewer open the
        // arrows belong to it, and a chapter turning behind an opaque overlay is
        // never what the reader meant.
        event.preventDefault();
        event.stopPropagation();
        if (!hasNeighbours) return;
        stepTo(event.key === "ArrowLeft" ? index - 1 : index + 1);
        return;
      }
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
  }, [onClose, resetView, zoomByFactor, hasNeighbours, index, stepTo]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={backdropRef}
      role="dialog"
      aria-modal="true"
      aria-label={t("Image")}
      tabIndex={-1}
      // The EPUB reader turns pages from a `window` keydown listener on the
      // bubble phase, so a `preventDefault()` here would not stop it. That
      // listener asks `allowsEpubPageTurn`, which refuses any target inside
      // `[data-reader-no-page-turn]` - and the attribute has to sit on this
      // dialog, because it is portaled to `document.body` and is no descendant
      // of the reader's own container. Focus starts here and the Tab trap keeps
      // it inside, so a key pressed anywhere in the viewer matches this node.
      data-reader-no-page-turn=""
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-[2px]"
    >
      <div
        // The stage fills the dialog, so the *window* is the box a zoomed
        // picture is clipped by. Sizing it to the picture instead (`max-h-full
        // max-w-full`) clipped the picture at its own natural box: at 2.5x a
        // 300x200 picture was 750x500 but only 348x248 of it could ever be
        // seen, and panning could not reveal the rest.
        className="absolute inset-0 flex items-center justify-center p-6"
        style={{ overflow: "hidden", touchAction: "none" }}
        onClick={(event) => {
          // The stage covers the backdrop now, so a click on the empty area
          // lands here rather than on the backdrop. It still dismisses, unless
          // it is the click that ended a pan, or a click on the picture that
          // pointer capture retargeted to the stage.
          if (event.target !== event.currentTarget) return;
          if (dragMovedRef.current) return;
          if (pressOnStageRef.current === false) return;
          onClose();
        }}
        onPointerDown={(event) => {
          pressOnStageRef.current = event.target === event.currentTarget;
          dragMovedRef.current = false;
          if (view.scale <= MIN_IMAGE_ZOOM) return;
          dragRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            originX: view.x,
            originY: view.y,
            captured: false,
          };
          // Capture only once a drag is under way (`onPointerMove`). Capturing
          // here retargeted the pointerup and click of a plain tap on the
          // picture to the stage, so that tap dismissed the viewer.
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          const x = drag.originX + event.clientX - drag.startX;
          const y = drag.originY + event.clientY - drag.startY;
          if (!dragMovedRef.current) {
            const travelled =
              Math.abs(event.clientX - drag.startX) +
              Math.abs(event.clientY - drag.startY);
            // A few pixels of jitter still count as a click, not a pan.
            dragMovedRef.current = travelled > 3;
            // The gesture is a pan now, so take the pointer: the picture must
            // keep following it even when it leaves the stage's box.
            if (dragMovedRef.current && !drag.captured) {
              drag.captured = true;
              event.currentTarget.setPointerCapture?.(event.pointerId);
            }
          }
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
          // A keyed node, so switching pictures replaces the element instead of
          // reusing it. React keeps one `<img>` and only rewrites `src`, and a
          // browser goes on painting the OLD picture until the new one decodes
          // — so a reader pressing Right on a large scan sees the same image
          // for a moment and presses again, skipping one.
          key={current.src}
          src={current.src}
          alt={current.alt}
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

      {/* The band spans the whole window, but only the toolbar in it is a
          control: without `pointer-events-none` the empty strip either side of
          the toolbar swallowed the click-to-dismiss the rest of the stage
          honours. The toolbar opts back in so its buttons still work. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center">
        <div
          role="toolbar"
          aria-label={t("Zoom level")}
          className="pointer-events-auto flex items-center gap-0.5 rounded-xl bg-white/10 px-1.5 py-1 text-white backdrop-blur"
        >
          {hasNeighbours && (
            <>
              <PreferenceButton
                label={t("Previous image")}
                icon={ChevronLeft}
                // Disabled rather than wrapping: the reader can see where the
                // list ends, and a wrap makes "left" mean two different things
                // depending on which picture happens to be on screen.
                disabled={atFirst}
                onClick={() => stepTo(index - 1)}
              />
              <span className="min-w-[44px] text-center text-[12px] tabular-nums text-white/80">
                {`${index + 1} / ${images.length}`}
              </span>
              <PreferenceButton
                label={t("Next image")}
                icon={ChevronRight}
                disabled={atLast}
                onClick={() => stepTo(index + 1)}
              />
              <span className="mx-1 h-4 w-px bg-white/20" aria-hidden />
            </>
          )}
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
