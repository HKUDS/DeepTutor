"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import {
  BookmarkPlus,
  Highlighter,
  MessageSquareQuote,
  MoreHorizontal,
  StickyNote,
  Underline,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";
import { useDevice } from "@/hooks/useDevice";
import {
  ANNOTATION_COLORS,
  ANNOTATION_SWATCH,
  type AnnotationColor,
} from "@/lib/reading-api";

export interface AnnotationPopoverProps {
  /** Viewport coordinates of the selection's end. */
  anchor: { x: number; y: number };
  quote: string;
  onHighlight: (color: AnnotationColor) => void;
  onUnderline: (color: AnnotationColor) => void;
  onNote: (note: string, color: AnnotationColor) => void;
  onCitation: (color: AnnotationColor) => void;
  onAsk: () => void;
  onDismiss: () => void;
  /**
   * AI actions on the selection, shown as a second row under the marking
   * tools. Without them the popover is the annotation toolbar it always was,
   * with "Ask about this" as its last icon.
   */
  aiActions?: PopoverAiAction[];
}

export interface PopoverAiAction {
  key: string;
  /** Short chip text ("Explain"); `title` carries the full name. */
  label: string;
  title: string;
  onClick: () => void;
}

/** Chips that fit on the row before the rest go behind ⋯. */
const INLINE_AI_ACTIONS = 3;

/** How far the sheet must be pulled down before the drag counts as "close". */
const DRAG_CLOSE_THRESHOLD = 48;

/**
 * Toolbar that appears over a selection.
 *
 * On a desktop it is positioned in fixed coordinates and clamped to the
 * window after mount, so a selection near the top or right edge still shows
 * the whole toolbar instead of being cut off — the failure people actually
 * hit, since the interesting text is often at the top of a page.
 *
 * Below 768px it is a bottom card instead (#916): the anchored popover that
 * a long-press summons competes with the system selection menu for the same
 * few pixels around the finger, so on a phone the panel drops to the bottom
 * of the screen. The collapsed rows fit without scrolling; the expanded
 * states — the note editor, the extra AI actions — get a capped, scrollable
 * body; and a drag handle offers pull-down-to-dismiss next to Escape and
 * tapping the page.
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
  onCitation,
  onAsk,
  onDismiss,
  aiActions,
}: AnnotationPopoverProps) {
  const { t } = useTranslation();
  const { isMobile } = useDevice();
  const ref = useRef<HTMLDivElement | null>(null);
  const [color, setColor] = useState<AnnotationColor>("yellow");
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const [overflowOpen, setOverflowOpen] = useState(false);
  const inlineAi = aiActions?.slice(0, INLINE_AI_ACTIONS) ?? [];
  const overflowAi = aiActions?.slice(INLINE_AI_ACTIONS) ?? [];
  const [position, setPosition] = useState({ left: anchor.x, top: anchor.y });

  // -- pull-down-to-dismiss ------------------------------------------------
  //
  // Only the handle drags; the body stays live so a scroll or a tap inside
  // the card never reads as "close". The threshold is generous: an accidental
  // nudge moves the sheet visually without closing it.
  const dragRef = useRef<{ id: number; startY: number } | null>(null);
  const [dragOffset, setDragOffset] = useState(0);
  const onHandlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = { id: event.pointerId, startY: event.clientY };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // jsdom / rare engines without capture: element handlers still fire.
    }
  };
  const onHandlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== event.pointerId) return;
    setDragOffset(Math.max(0, event.clientY - drag.startY));
  };
  const onHandlePointerEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.id !== event.pointerId) return;
    dragRef.current = null;
    const travelled = Math.max(0, event.clientY - drag.startY);
    setDragOffset(0);
    if (travelled >= DRAG_CLOSE_THRESHOLD) onDismiss();
  };

  useLayoutEffect(() => {
    if (isMobile) return;
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
  }, [anchor.x, anchor.y, isMobile, noteOpen, overflowOpen]);

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

  // The rows are shared by both presentations; only the frame they sit in
  // differs. `expanded` is what makes the body long: the note editor and the
  // overflow action list are the states whose content can outgrow a thumb's
  // reach, so they are the ones that switch the body to capped-and-scrollable.
  const expanded = noteOpen || overflowOpen;

  const body = (
    <>
      <div className="flex items-center gap-1">
        <div className="flex items-center gap-0.5 pr-1">
          {ANNOTATION_COLORS.map((swatch) => (
            <Tooltip key={swatch} label={t(swatchLabel(swatch))} side="top">
              <button
                type="button"
                aria-label={t(swatchLabel(swatch))}
                aria-pressed={color === swatch}
                onClick={() => setColor(swatch)}
                className={`h-5 w-5 rounded-full border transition ${
                  color === swatch
                    ? "border-[var(--foreground)] scale-110"
                    : "border-black/10 hover:scale-105"
                }`}
                style={{ background: ANNOTATION_SWATCH[swatch] }}
              />
            </Tooltip>
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
          icon={BookmarkPlus}
          label={t("Save citation")}
          onClick={() => onCitation(color)}
        />
        {aiActions ? null : (
          <IconButton
            icon={MessageSquareQuote}
            label={t("Ask about this")}
            onClick={onAsk}
          />
        )}
      </div>

      {aiActions && (
        <div className="mt-1.5 flex items-center gap-1 border-t border-[var(--border)] pt-1.5">
          <Tooltip label={t("Ask about this")} side="bottom">
            <button
              type="button"
              aria-label={t("Ask about this")}
              onClick={onAsk}
              className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-2.5 text-[12px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              <MessageSquareQuote size={13} />
              {t("Ask")}
            </button>
          </Tooltip>
          {inlineAi.map((action) => (
            <AiChip key={action.key} action={action} />
          ))}
          {overflowAi.length > 0 && (
            <IconButton
              icon={MoreHorizontal}
              label={t("More actions")}
              active={overflowOpen}
              onClick={() => setOverflowOpen((open) => !open)}
            />
          )}
        </div>
      )}

      {overflowOpen && overflowAi.length > 0 && (
        <div className="mt-1 grid gap-0.5 border-t border-[var(--border)] pt-1">
          {overflowAi.map((action) => (
            <button
              key={action.key}
              type="button"
              onClick={action.onClick}
              className="rounded-lg px-2 py-1.5 text-left text-[12px] text-[var(--foreground)] transition hover:bg-[var(--muted)]"
            >
              {action.title}
            </button>
          ))}
        </div>
      )}

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
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--ring)_20%,transparent)]"
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
    </>
  );

  if (isMobile) {
    return (
      <div
        ref={ref}
        role="dialog"
        aria-label={t("Annotate selection")}
        style={{ transform: dragOffset ? `translateY(${dragOffset}px)` : undefined }}
        className="dt-reader-sheet fixed inset-x-0 bottom-0 z-[70] rounded-t-2xl border-t border-[var(--border)] bg-[var(--popover)] pb-[calc(env(safe-area-inset-bottom)+10px)] shadow-[0_-12px_40px_-16px_rgba(0,0,0,0.45)]"
      >
        <div
          data-testid="sheet-handle"
          aria-hidden
          onPointerDown={onHandlePointerDown}
          onPointerMove={onHandlePointerMove}
          onPointerUp={onHandlePointerEnd}
          onPointerCancel={onHandlePointerEnd}
          className="flex cursor-grab touch-none justify-center pb-0.5 pt-2"
        >
          <span className="h-1.5 w-10 rounded-full bg-[var(--muted-foreground)]/40" />
        </div>
        <div
          data-scroll={expanded ? "long" : "short"}
          className={`px-2 ${
            expanded
              ? "max-h-[60dvh] overflow-y-auto overscroll-contain"
              : ""
          }`}
        >
          {body}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={t("Annotate selection")}
      style={{ left: position.left, top: position.top }}
      className="dt-reader-popover fixed z-[70] w-max max-w-[min(360px,92vw)] rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1.5 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.35)]"
    >
      {body}
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
    <Tooltip label={label} side="bottom">
      <button
        type="button"
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
    </Tooltip>
  );
}

function AiChip({ action }: { action: PopoverAiAction }) {
  return (
    <Tooltip label={action.title} side="bottom">
      <button
        type="button"
        aria-label={action.title}
        onClick={action.onClick}
        className="inline-flex h-7 items-center rounded-lg px-2 text-[12px] font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        {action.label}
      </button>
    </Tooltip>
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
