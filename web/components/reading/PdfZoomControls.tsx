"use client";

import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  DEFAULT_PDF_ZOOM,
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
  canZoomIn,
  canZoomOut,
  percentFor,
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
  /** False when a further step would not change the drawn width. */
  canZoomIn: boolean;
  canZoomOut: boolean;
  /**
   * The percentage a ladder stop actually lands at on this page.
   *
   * The toolbar shows what landed, so a row labelled with the request made the
   * two disagree: `MIN_PAGE_WIDTH` (240px) is above a Letter page's 25%
   * (204px), so picking "25%" drew 29% and the toolbar said 29% while the menu
   * still claimed 25%. Rows print the landed value now.
   */
  percentFor: (scale: number) => number;
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
  const menuRef = useRef<HTMLDivElement | null>(null);

  // The ref wraps the trigger *and* the menu, so a pointerdown on a menu row is
  // not read as "outside" before that row's click fires.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const root = rootRef.current;
      if (root && !root.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      // `preventDefault()` alone cannot keep the Escape from the Guided
      // Learning handler: that one listens on `document` and only steps aside
      // for a visible `[role=dialog]`, while this menu is a `role="menu"`. Both
      // listeners sit on the same node, and `preventDefault` never stops
      // delivery to the other. Stopping propagation here is what actually
      // keeps one Escape from closing the menu and leaving learning mode.
      event.stopPropagation();
      // Focus goes back to the trigger the menu belongs to, so a keyboard user
      // is not dropped on `<body>` after closing.
      rootRef.current?.querySelector<HTMLElement>('[aria-haspopup="menu"]')?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    // Capture phase: this runs before the learning-mode listener regardless of
    // which one registered first.
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open]);

  // Both limits come from the parent, which knows the page geometry the canvas
  // budget depends on. Reading them off the requested scale here was wrong: the
  // budget can clamp a 4× request to 211%, so comparing `preference.scale`
  // against MAX_PDF_ZOOM left zoom-in enabled while every press was a no-op.
  const atFloor = !canZoomOut;
  const atCeiling = !canZoomIn;

  return (
    <div
      // The wrapper spans the pane's whole width so the toolbar can centre in
      // it, but it must never be a hit target: it is an absolutely positioned
      // sibling of the scroll container, so a pointer-opaque wrapper would
      // swallow wheel/ctrl+wheel, selection and annotation clicks across the
      // bottom band of every page. Only the toolbar itself opts back in.
      // `opacity-0` hides the bar but does not remove it from the tab order, so
      // a keyboard user could land on controls they cannot see. `focus-within`
      // reveals it the moment focus enters, which keeps the bar usable without
      // making it a hit target while hidden (`pointer-events-none` above).
      className={`pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center transition-opacity duration-150 focus-within:opacity-100 ${
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
        // Arrow keys are handled here, on the toolbar, not on the menu: when the
        // menu opens, focus is still on the trigger — a SIBLING of the menu — so
        // a handler on the menu never sees the keydown. The toolbar contains
        // both, so this fires wherever focus is inside the bar.
        onKeyDown={(event) => {
          if (!open) return;
          const rows = Array.from(
            menuRef.current?.querySelectorAll<HTMLElement>(
              '[role="menuitemradio"]',
            ) ?? [],
          );
          if (rows.length === 0) return;
          const at = rows.indexOf(document.activeElement as HTMLElement);
          const focusAt = (index: number) =>
            rows[(index + rows.length) % rows.length].focus();
          if (event.key === "ArrowDown") {
            event.preventDefault();
            focusAt(at < 0 ? 0 : at + 1);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            focusAt(at < 0 ? rows.length - 1 : at - 1);
          } else if (event.key === "Home") {
            event.preventDefault();
            focusAt(0);
          } else if (event.key === "End") {
            event.preventDefault();
            focusAt(rows.length - 1);
          }
        }}
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
          // The percentage is the only feedback a step produces for a reader who
          // cannot see the page resize, so the value is announced when it
          // changes. `polite` rather than `assertive`: a wheel gesture produces
          // many updates and must not interrupt whatever is being read.
          aria-live="polite"
          aria-atomic="true"
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
            ref={menuRef}
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
                // The rows are one choice among many, which is a radio group:
                // `aria-checked` is what a screen reader reads out, and
                // `aria-current` belongs to navigation landmarks instead.
                role="menuitemradio"
                aria-checked={preference.mode === row.mode}
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
                role="menuitemradio"
                // `aria-checked` is what a radio row exposes; `aria-current`
                // is for navigation landmarks and was simply the wrong
                // attribute here.
                aria-checked={
                  preference.mode === "fixed" &&
                  Math.abs(preference.scale - scale) < 0.001
                }
                onClick={() => {
                  onSelect({ mode: "fixed", scale });
                  setOpen(false);
                }}
                className="flex h-8 w-full items-center rounded-lg px-2.5 text-left text-[12px] tabular-nums hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)]"
              >
                {`${percentFor(scale)}%`}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
