"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Highlighter,
  MessageSquareQuote,
  StickyNote,
  Underline,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { ANNOTATION_COLORS, type AnnotationColor } from "@/lib/reading-api";

const SWATCH: Record<AnnotationColor, string> = {
  yellow: "#facd5a",
  green: "#8cdb94",
  blue: "#7ac0fa",
  pink: "#faa1c7",
  purple: "#c7aefa",
};

export interface AnnotationPopoverProps {
  /** Viewport coordinates of the selection's end. */
  anchor: { x: number; y: number };
  quote: string;
  onHighlight: (color: AnnotationColor) => void;
  onUnderline: (color: AnnotationColor) => void;
  onNote: (note: string, color: AnnotationColor) => void;
  onAsk: () => void;
  onDismiss: () => void;
}

/**
 * Toolbar that appears over a selection.
 *
 * Positioned in fixed coordinates and then clamped to the window after mount, so
 * a selection near the top or right edge still shows the whole toolbar instead of
 * being cut off — the failure people actually hit, since the interesting text is
 * often at the top of a page.
 *
 * Dismissal is on Escape and on pointerdown outside. Deliberately not on blur:
 * clicking a colour swatch blurs the toolbar, and a blur-based dismissal would
 * race the click and eat every second annotation.
 */
export function AnnotationPopover({
  anchor,
  quote,
  onHighlight,
  onUnderline,
  onNote,
  onAsk,
  onDismiss,
}: AnnotationPopoverProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement | null>(null);
  const [color, setColor] = useState<AnnotationColor>("yellow");
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const [position, setPosition] = useState({ left: anchor.x, top: anchor.y });

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const box = element.getBoundingClientRect();
    const margin = 10;
    // Prefer above the selection; flip below when there is no room up there.
    let top = anchor.y - box.height - margin;
    if (top < margin) top = anchor.y + 24;
    const left = Math.min(
      Math.max(margin, anchor.x - box.width / 2),
      window.innerWidth - box.width - margin,
    );
    setPosition({
      left,
      top: Math.min(top, window.innerHeight - box.height - margin),
    });
  }, [anchor.x, anchor.y, noteOpen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onDismiss();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onDismiss();
    };
    document.addEventListener("keydown", onKey);
    // Capture phase: the reader's own mouseup handler would otherwise clear the
    // selection before this listener ran.
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [onDismiss]);

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={t("Annotate selection")}
      style={{ left: position.left, top: position.top }}
      className="dt-reader-popover fixed z-[70] w-max max-w-[min(360px,92vw)] rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1.5 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.35)]"
    >
      <div className="flex items-center gap-1">
        <div className="flex items-center gap-0.5 pr-1">
          {ANNOTATION_COLORS.map((swatch) => (
            <button
              key={swatch}
              type="button"
              title={t(swatchLabel(swatch))}
              aria-label={t(swatchLabel(swatch))}
              aria-pressed={color === swatch}
              onClick={() => setColor(swatch)}
              className={`h-5 w-5 rounded-full border transition ${
                color === swatch
                  ? "border-[var(--foreground)] scale-110"
                  : "border-black/10 hover:scale-105"
              }`}
              style={{ background: SWATCH[swatch] }}
            />
          ))}
        </div>
        <span className="h-5 w-px bg-[var(--border)]" aria-hidden />
        <IconButton
          icon={Highlighter}
          label={t("Highlight")}
          onClick={() => onHighlight(color)}
        />
        <IconButton
          icon={Underline}
          label={t("Underline")}
          onClick={() => onUnderline(color)}
        />
        <IconButton
          icon={StickyNote}
          label={t("Add note")}
          active={noteOpen}
          onClick={() => setNoteOpen((open) => !open)}
        />
        <IconButton
          icon={MessageSquareQuote}
          label={t("Ask about this")}
          onClick={onAsk}
        />
      </div>

      {noteOpen && (
        <div className="mt-1.5 border-t border-[var(--border)] pt-1.5">
          <p className="mb-1 line-clamp-2 px-1 text-[11px] italic text-[var(--muted-foreground)]">
            “{quote}”
          </p>
          <textarea
            autoFocus
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                onNote(note, color);
              }
            }}
            rows={3}
            placeholder={t("Your note…")}
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/20"
          />
          <div className="mt-1 flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-lg px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={() => onNote(note, color)}
              className="rounded-lg bg-[var(--primary)] px-2.5 py-1 text-[11px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              {t("Save note")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function IconButton({
  icon: Icon,
  label,
  onClick,
  active,
}: {
  icon: typeof Highlighter;
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg transition ${
        active
          ? "bg-[var(--muted)] text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={14} />
    </button>
  );
}

function swatchLabel(color: AnnotationColor): string {
  switch (color) {
    case "green":
      return "Green";
    case "blue":
      return "Blue";
    case "pink":
      return "Pink";
    case "purple":
      return "Purple";
    default:
      return "Yellow";
  }
}
