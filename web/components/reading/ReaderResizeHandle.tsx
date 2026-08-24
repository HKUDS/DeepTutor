"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  READER_STEP_PX,
  READER_WIDTH_KEY,
  READER_WIDTH_VAR,
  clampReaderWidth,
  parseStoredWidth,
} from "@/lib/reading-split";

/**
 * The draggable seam between the document and the conversation.
 *
 * The width is **not** React state. Both sides of the split read the same
 * `--reader-width` custom property — the pane for its own width, the chat shell
 * for its left padding — so the drag writes that one property and both edges
 * move together, locked, without re-rendering either tree. A pointermove that
 * re-rendered the message list would be visibly janky; this is the same approach
 * the session viewer panel already uses for its edge.
 *
 * Also focusable: arrow keys nudge, Home resets. A split that can only be set by
 * dragging is unusable for anyone not using a mouse, and this is the kind of
 * control people do reach for by keyboard.
 */

function containerWidth(element: HTMLElement | null): number {
  const shell = element?.closest<HTMLElement>(".dt-reader-shell");
  const parent = shell?.parentElement;
  return parent?.getBoundingClientRect().width ?? 0;
}

function containerLeft(element: HTMLElement | null): number {
  const shell = element?.closest<HTMLElement>(".dt-reader-shell");
  return shell?.getBoundingClientRect().left ?? 0;
}

function applyWidth(px: number): void {
  document.documentElement.style.setProperty(READER_WIDTH_VAR, `${px}px`);
}

/**
 * Apply a width with the easing suppressed, then restore it.
 *
 * The chat side animates its padding so that *opening* the reader glides. A
 * keyboard nudge is not an opening — it is a direct adjustment, and easing each
 * 24px step over 240ms makes the seam feel like it is dragging behind the key
 * press. The drag path suppresses the same transition for its whole duration;
 * this is the discrete equivalent.
 */
function applyWidthImmediately(px: number): void {
  const root = document.documentElement;
  root.dataset.readerResizing = "true";
  applyWidth(px);
  // Two frames: one for the write to land, one for the layout to settle before
  // easing is allowed back. `setTimeout(0)` would sometimes restore it early and
  // animate the tail of the step.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      delete root.dataset.readerResizing;
    });
  });
}

/** Current width in px, measured rather than remembered. */
function currentWidth(element: HTMLElement | null): number {
  const shell = element?.closest<HTMLElement>(".dt-reader-shell");
  return shell?.getBoundingClientRect().width ?? 0;
}

export function ReaderResizeHandle() {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement | null>(null);

  // Restore after mount, not during render: the server has no localStorage, and
  // the CSS fallback (a percentage) is what both sides use until then.
  useEffect(() => {
    let stored: number | null = null;
    try {
      stored = parseStoredWidth(window.localStorage.getItem(READER_WIDTH_KEY));
    } catch {
      // Storage unavailable — keep the CSS default.
    }
    if (stored === null) return;
    applyWidthImmediately(
      clampReaderWidth(stored, containerWidth(ref.current)),
    );
  }, []);

  const persist = useCallback((px: number) => {
    try {
      window.localStorage.setItem(READER_WIDTH_KEY, String(px));
    } catch {
      // Non-fatal: the split still holds for this session.
    }
  }, []);

  const startDrag = useCallback(
    (event: React.PointerEvent) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const element = ref.current;
      const available = containerWidth(element);
      const left = containerLeft(element);

      // Killing the transition for the duration is what makes the edge track the
      // cursor frame-for-frame instead of easing along behind it.
      document.documentElement.dataset.readerResizing = "true";
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";

      let frame = 0;
      let pendingX = event.clientX;
      let latest = clampReaderWidth(pendingX - left, available);

      const apply = () => {
        frame = 0;
        latest = clampReaderWidth(pendingX - left, available);
        applyWidth(latest);
      };
      const onMove = (moveEvent: PointerEvent) => {
        // Coalesce to one write per frame: pointermove fires faster than the
        // display refreshes.
        pendingX = moveEvent.clientX;
        if (!frame) frame = requestAnimationFrame(apply);
      };
      const onUp = () => {
        if (frame) cancelAnimationFrame(frame);
        delete document.documentElement.dataset.readerResizing;
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        persist(latest);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      // A cancelled pointer (a system gesture taking over) must still clean up,
      // or the page is left with text selection disabled and a resize cursor.
      window.addEventListener("pointercancel", onUp);
    },
    [persist],
  );

  const nudge = useCallback(
    (delta: number) => {
      const element = ref.current;
      const next = clampReaderWidth(
        currentWidth(element) + delta,
        containerWidth(element),
      );
      applyWidthImmediately(next);
      persist(next);
    },
    [persist],
  );

  const reset = useCallback(() => {
    document.documentElement.style.removeProperty(READER_WIDTH_VAR);
    try {
      window.localStorage.removeItem(READER_WIDTH_KEY);
    } catch {
      // Nothing to clean up.
    }
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const step = event.shiftKey ? READER_STEP_PX * 4 : READER_STEP_PX;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        nudge(-step);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        nudge(step);
      } else if (event.key === "Home") {
        event.preventDefault();
        reset();
      }
    },
    [nudge, reset],
  );

  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("Resize the reader")}
      tabIndex={0}
      onPointerDown={startDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={reset}
      title={t("Drag to resize · double-click to reset")}
      className="dt-reader-resize group/resize absolute inset-y-0 right-0 z-20 flex w-3 translate-x-1/2 cursor-col-resize items-center justify-center outline-none"
    >
      {/* The visible line is thin; the hit area above is comfortable. */}
      <span
        aria-hidden
        className="h-full w-px bg-transparent transition-colors duration-150 group-hover/resize:bg-[var(--ring)]/50 group-focus-visible/resize:bg-[var(--ring)]"
      />
      <span
        aria-hidden
        className="absolute h-8 w-1 rounded-full bg-transparent transition-colors duration-150 group-hover/resize:bg-[var(--ring)]/70 group-focus-visible/resize:bg-[var(--ring)]"
      />
    </div>
  );
}
