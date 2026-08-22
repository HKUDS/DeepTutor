"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AnnotationItem, UnitKind } from "@/lib/reading-api";
import { getUnitText } from "@/lib/reading-api";
import { segmentTextByQuotes } from "@/lib/reading-quote-locator";
import { cleanQuote } from "@/lib/reading-selection";
import type { JumpRequest, SelectionPayload } from "./PdfDocumentView";

const COLOR_INK: Record<string, string> = {
  yellow: "250 220 90",
  green: "140 219 148",
  blue: "122 192 250",
  pink: "250 161 199",
  purple: "199 174 250",
};

export interface TextUnitViewProps {
  materialId: string;
  unit: UnitKind;
  unitCount: number;
  annotations: AnnotationItem[];
  jump: JumpRequest | null;
  highlightedAnnotationId?: string | null;
  onSelection: (payload: SelectionPayload | null) => void;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  onVisibleLocatorChange?: (locator: number) => void;
}

/**
 * One-unit-at-a-time reader for materials with no faithful raw view.
 *
 * EPUB, DOCX, slides and plain text are read from extracted text, so there is no
 * page image to overlay. Highlights are therefore anchored to the *quote* rather
 * than to geometry: the text reflows with the pane, and a stored rectangle would
 * drift away from its words. Selections made here are saved with no rects, which
 * is exactly what the Markdown export consumes.
 */
export function TextUnitView({
  materialId,
  unit,
  unitCount,
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
}: TextUnitViewProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [locator, setLocator] = useState(1);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLocator(1);
  }, [materialId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const unitText = await getUnitText(materialId, locator);
        if (!cancelled) setText(unitText.text);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t("Could not load this section."),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [materialId, locator, t]);

  useEffect(() => {
    onVisibleLocatorChange?.(locator);
  }, [locator, onVisibleLocatorChange]);

  // Responding to a command from outside React (the assistant asked the reader
  // to move), not deriving state from props — so setting state here is the
  // intended shape. The locator is also user-controlled via the arrows, which is
  // why it cannot simply be computed from `jump`.
  useEffect(() => {
    if (!jump) return;
    const target = Math.min(Math.max(1, jump.locator), unitCount);
    setLocator(target);
    // Assigned rather than animated: programmatic smooth scrolling is a silent
    // no-op in some embedded browsers, and landing at the top of the section is
    // the part that matters. CSS `scroll-behavior` supplies the easing.
    if (containerRef.current) containerRef.current.scrollTop = 0;
  }, [jump, unitCount]);

  const runs = useMemo(
    () =>
      segmentTextByQuotes(
        text,
        annotations.filter((a) => a.locator === locator),
      ),
    [text, annotations, locator],
  );

  const handlePointerUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      onSelection(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!containerRef.current?.contains(range.commonAncestorContainer)) {
      onSelection(null);
      return;
    }
    const quote = cleanQuote(selection.toString());
    if (!quote) {
      onSelection(null);
      return;
    }
    const rects = [...range.getClientRects()];
    const last = rects[rects.length - 1];
    onSelection({
      locator,
      quote,
      // No geometry: a reflowing text view has none worth storing.
      rects: [],
      anchor: last
        ? { x: last.left + last.width / 2, y: last.top }
        : { x: 0, y: 0 },
    });
  }, [locator, onSelection]);

  const canPrev = locator > 1;
  const canNext = locator < unitCount;

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      <div className="flex items-center justify-center gap-2 border-b border-[var(--border)] px-4 py-2">
        <button
          type="button"
          disabled={!canPrev}
          onClick={() => setLocator((current) => Math.max(1, current - 1))}
          className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-35 disabled:hover:bg-transparent"
          aria-label={t("Previous")}
        >
          <ChevronLeft size={15} />
        </button>
        <span className="min-w-[120px] text-center font-mono text-[11px] tabular-nums text-[var(--muted-foreground)]">
          {t("{{unit}} {{n}} of {{total}}", {
            unit: t(unitLabel(unit)),
            n: locator,
            total: unitCount,
          })}
        </span>
        <button
          type="button"
          disabled={!canNext}
          onClick={() =>
            setLocator((current) => Math.min(unitCount, current + 1))
          }
          className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-35 disabled:hover:bg-transparent"
          aria-label={t("Next")}
        >
          <ChevronRight size={15} />
        </button>
      </div>

      <div
        ref={containerRef}
        data-reader-unit={locator}
        onMouseUp={handlePointerUp}
        className="dt-reader-scroll flex-1 overflow-y-auto overscroll-contain px-8 py-7"
      >
        {loading ? (
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" />
            {t("Loading…")}
          </div>
        ) : error ? (
          <p className="text-[12px] text-[var(--muted-foreground)]">{error}</p>
        ) : (
          <article className="mx-auto max-w-[68ch] whitespace-pre-wrap font-serif text-[15px] leading-[1.75] text-[var(--foreground)] selection:bg-[var(--primary)]/20">
            {runs.length === 0 ? (
              <span className="text-[var(--muted-foreground)]">
                {t("This section has no extractable text.")}
              </span>
            ) : (
              runs.map((run, index) =>
                run.mark ? (
                  <mark
                    key={index}
                    title={run.mark.note || undefined}
                    onClick={() =>
                      onAnnotationClick?.(run.mark as AnnotationItem)
                    }
                    className={`cursor-pointer rounded-[2px] px-[1px] text-[var(--foreground)] ${
                      run.mark.annotation_id === highlightedAnnotationId
                        ? "ring-2 ring-[var(--ring)]"
                        : ""
                    }`}
                    style={{
                      background:
                        run.mark.kind === "underline"
                          ? "transparent"
                          : `rgb(${COLOR_INK[run.mark.color] ?? COLOR_INK.yellow} / 0.55)`,
                      borderBottom:
                        run.mark.kind === "underline"
                          ? `2px solid rgb(${COLOR_INK[run.mark.color] ?? COLOR_INK.yellow})`
                          : undefined,
                    }}
                  >
                    {run.text}
                  </mark>
                ) : (
                  <span key={index}>{run.text}</span>
                ),
              )
            )}
          </article>
        )}
      </div>
    </div>
  );
}

/** Translatable label for a unit kind. Keys are literal so i18n can find them. */
export function unitLabel(unit: UnitKind): string {
  switch (unit) {
    case "chapter":
      return "Chapter";
    case "slide":
      return "Slide";
    case "section":
      return "Section";
    default:
      return "Page";
  }
}
