"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ALargeSmall,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Minus,
  Plus,
  Rows3,
  SunMoon,
} from "lucide-react";
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

const READER_PREFS_KEY = "dt.reader.textPreferences";
type ReaderTheme = "auto" | "sepia" | "night";

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
  const [fontSize, setFontSize] = useState(15);
  const [lineWidth, setLineWidth] = useState(68);
  const [serif, setSerif] = useState(true);
  const [readerTheme, setReaderTheme] = useState<ReaderTheme>("auto");

  useEffect(() => {
    try {
      const value = JSON.parse(window.localStorage.getItem(READER_PREFS_KEY) || "{}");
      if (typeof value.fontSize === "number") {
        setFontSize(Math.min(22, Math.max(12, value.fontSize)));
      }
      if (typeof value.lineWidth === "number") {
        setLineWidth(Math.min(88, Math.max(48, value.lineWidth)));
      }
      if (typeof value.serif === "boolean") setSerif(value.serif);
      if (["auto", "sepia", "night"].includes(value.readerTheme)) {
        setReaderTheme(value.readerTheme);
      }
    } catch {
      // Invalid or unavailable local storage falls back to readable defaults.
    }
  }, []);

  const updatePreferences = useCallback(
    (next: Partial<{
      fontSize: number;
      lineWidth: number;
      serif: boolean;
      readerTheme: ReaderTheme;
    }>) => {
      const merged = { fontSize, lineWidth, serif, readerTheme, ...next };
      setFontSize(merged.fontSize);
      setLineWidth(merged.lineWidth);
      setSerif(merged.serif);
      setReaderTheme(merged.readerTheme);
      try {
        window.localStorage.setItem(READER_PREFS_KEY, JSON.stringify(merged));
      } catch {
        // Preferences still apply for the current session.
      }
    },
    [fontSize, lineWidth, readerTheme, serif],
  );

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
    <div
      className="flex h-full flex-col"
      style={
        readerTheme === "sepia"
          ? { background: "#f4ecd8", color: "#473c2c" }
          : readerTheme === "night"
            ? { background: "#16181d", color: "#e8e5df" }
            : undefined
      }
    >
      <div className="flex items-center justify-between gap-2 overflow-x-auto border-b border-[var(--border)] px-2 py-2 sm:px-3">
        <div className="flex shrink-0 items-center gap-0.5">
          <PreferenceButton
            label={t("Smaller text")}
            icon={Minus}
            disabled={fontSize <= 12}
            onClick={() => updatePreferences({ fontSize: Math.max(12, fontSize - 1) })}
          />
          <PreferenceButton
            label={t("Larger text")}
            icon={Plus}
            disabled={fontSize >= 22}
            onClick={() => updatePreferences({ fontSize: Math.min(22, fontSize + 1) })}
          />
          <PreferenceButton
            label={serif ? t("Use sans-serif font") : t("Use serif font")}
            icon={ALargeSmall}
            active={!serif}
            onClick={() => updatePreferences({ serif: !serif })}
          />
          <PreferenceButton
            label={t("Change line width")}
            icon={Rows3}
            onClick={() =>
              updatePreferences({ lineWidth: lineWidth >= 88 ? 48 : lineWidth + 20 })
            }
          />
          <PreferenceButton
            label={t("Change reading theme")}
            icon={SunMoon}
            active={readerTheme !== "auto"}
            onClick={() =>
              updatePreferences({
                readerTheme:
                  readerTheme === "auto"
                    ? "sepia"
                    : readerTheme === "sepia"
                      ? "night"
                      : "auto",
              })
            }
          />
        </div>
        <div className="flex shrink-0 items-center gap-1 sm:gap-2">
          <button
            type="button"
            disabled={!canPrev}
            onClick={() => setLocator((current) => Math.max(1, current - 1))}
            className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label={t("Previous")}
          >
            <ChevronLeft size={15} />
          </button>
          <span className="min-w-[44px] text-center font-mono text-[11px] tabular-nums text-[var(--muted-foreground)] sm:hidden">
            {locator}/{unitCount}
          </span>
          <span className="hidden min-w-[120px] text-center font-mono text-[11px] tabular-nums text-[var(--muted-foreground)] sm:inline">
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
      </div>

      <div
        ref={containerRef}
        data-reader-unit={locator}
        onMouseUp={handlePointerUp}
        className="dt-reader-scroll flex-1 overflow-y-auto overscroll-contain px-4 py-6 sm:px-8 sm:py-7"
      >
        {loading ? (
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" />
            {t("Loading…")}
          </div>
        ) : error ? (
          <p className="text-[12px] text-[var(--muted-foreground)]">{error}</p>
        ) : (
          <article
            className={`mx-auto whitespace-pre-wrap leading-[1.75] selection:bg-[var(--primary)]/20 ${serif ? "font-serif" : "font-sans"}`}
            style={{
              maxWidth: `${lineWidth}ch`,
              fontSize: `${fontSize}px`,
              color: readerTheme === "auto" ? "var(--foreground)" : "inherit",
            }}
          >
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

function PreferenceButton({
  label,
  icon: Icon,
  onClick,
  active = false,
  disabled = false,
}: {
  label: string;
  icon: typeof Minus;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg transition disabled:opacity-35 ${
        active
          ? "bg-[var(--primary)]/12 text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={13} />
    </button>
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
