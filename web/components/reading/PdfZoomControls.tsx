"use client";

import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  DEFAULT_PDF_ZOOM,
  MAX_PDF_ZOOM,
  MIN_PDF_ZOOM,
  PDF_ZOOM_OPTIONS,
  type PdfZoomPreference,
} from "@/lib/reading-zoom";
import { PreferenceButton } from "./ReaderDisplayControls";

/**
 * The PDF reader's zoom bar.
 *
 * Floats at the bottom of the pane rather than inside the scroll container, so
 * it does not scroll away with the pages. The percentage is the width that
 * actually landed: a 400% request clamped by the canvas budget shows 215%, and
 * the menu marks the stop that produces it.
 */
export function PdfZoomControls({
  preference,
  effectivePercent,
  visible,
  onZoomIn,
  onZoomOut,
  onSelect,
  onReset,
  onActiveChange,
}: {
  preference: PdfZoomPreference;
  /** The percentage actually rendered, which clamping can lower. */
  effectivePercent: number;
  visible: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onSelect: (next: PdfZoomPreference) => void;
  onReset: () => void;
  /** Reports pointer presence so hovering the bar does not hide it. */
  onActiveChange: (active: boolean) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // The ref wraps the trigger *and* the menu, so a pointerdown on a menu row is
  // not read as "outside" before that row's click fires.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const root = rootRef.current;
      if (root && !root.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const atFloor = effectivePercent <= Math.round(MIN_PDF_ZOOM * 100);
  const atCeiling =
    preference.mode === "fixed" && preference.scale >= MAX_PDF_ZOOM;

  return (
    <div
      // The wrapper spans the pane's whole width so the toolbar can centre in
      // it, but it must never be a hit target: it is an absolutely positioned
      // sibling of the scroll container, so a pointer-opaque wrapper would
      // swallow wheel/ctrl+wheel, selection and annotation clicks across the
      // bottom band of every page. Only the toolbar itself opts back in.
      className={`pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center transition-opacity duration-150 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
    >
      <div
        ref={rootRef}
        role="toolbar"
        // The pointer handlers live on the toolbar, not the wrapper: with the
        // wrapper transparent they would never fire, and the bar would hide
        // while it is being used.
        onPointerEnter={() => onActiveChange(true)}
        onPointerLeave={() => onActiveChange(false)}
        // Marks the bar as part of the reader for the keyboard shortcuts, which
        // otherwise only look at the scroll root (a sibling of this element).
        data-pdf-zoom-controls=""
        aria-label={t("Zoom level")}
        className="pointer-events-auto relative flex items-center gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-1.5 py-1 text-[var(--foreground)] shadow-[0_8px_24px_rgba(0,0,0,0.12)]"
      >
        <PreferenceButton
          label={t("Zoom out")}
          icon={ZoomOut}
          disabled={atFloor}
          onClick={onZoomOut}
        />
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={t("Zoom level")}
          onClick={() => setOpen((value) => !value)}
          className="h-7 min-w-[58px] rounded-lg px-2 text-[12px] tabular-nums transition hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)]"
        >
          {preference.mode === "text"
            ? t("Fit text")
            : preference.mode === "fit"
              ? t("Fit page")
              : `${effectivePercent}%`}
        </button>
        <PreferenceButton
          label={t("Zoom in")}
          icon={ZoomIn}
          disabled={atCeiling}
          onClick={onZoomIn}
        />
        <PreferenceButton
          label={t("Reset zoom")}
          icon={RotateCcw}
          onClick={onReset}
        />

        {open && (
          <div
            role="menu"
            aria-label={t("Zoom level")}
            className="absolute bottom-full left-1/2 mb-2 min-w-[132px] -translate-x-1/2 rounded-xl border border-[var(--border)] bg-[var(--background)] p-1.5 shadow-xl"
          >
            {(
              [
                { mode: "text", label: t("Fit text") },
                { mode: "fit", label: t("Fit page") },
              ] as const
            ).map((row) => (
              <button
                key={row.mode}
                type="button"
                role="menuitem"
                aria-current={preference.mode === row.mode ? "page" : undefined}
                onClick={() => {
                  onSelect({ mode: row.mode });
                  setOpen(false);
                }}
                className="flex h-8 w-full items-center rounded-lg px-2.5 text-left text-[12px] hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)]"
              >
                {row.label}
              </button>
            ))}
            {PDF_ZOOM_OPTIONS.map((scale) => (
              <button
                key={scale}
                type="button"
                role="menuitem"
                aria-current={
                  preference.mode === "fixed" &&
                  Math.abs(preference.scale - scale) < 0.001
                    ? "page"
                    : undefined
                }
                onClick={() => {
                  onSelect({ mode: "fixed", scale });
                  setOpen(false);
                }}
                className="flex h-8 w-full items-center rounded-lg px-2.5 text-left text-[12px] tabular-nums hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)]"
              >
                {`${Math.round(scale * 100)}%`}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
