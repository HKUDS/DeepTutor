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
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type {
  AnnotationItem,
  BilingualGroup,
  ContentFormat,
  UnitKind,
} from "@/lib/reading-api";
import { getBilingualUnit, getUnitText } from "@/lib/reading-api";
import { segmentTextByQuotes } from "@/lib/reading-quote-locator";
import { cleanQuote } from "@/lib/reading-selection";
import { toRecogitoTextAnnotation } from "@/lib/reading-w3c-annotations";
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
  contentFormat?: ContentFormat;
  bilingualAvailable?: boolean;
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
  contentFormat = "plain_text",
  bilingualAvailable = false,
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
}: TextUnitViewProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const articleRef = useRef<HTMLElement | null>(null);
  const textSelectorToolsRef = useRef<{
    rangeToSelector: (
      range: Range,
      container: HTMLElement,
    ) => { quote: string; start: number; end: number };
    getQuoteContext: (
      range: Range,
      container: HTMLElement,
    ) => { prefix: string; suffix: string };
  } | null>(null);
  const [locator, setLocator] = useState(1);
  const [text, setText] = useState("");
  const [bilingualGroups, setBilingualGroups] = useState<BilingualGroup[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
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
        const [unitText, bilingual] = await Promise.all([
          getUnitText(materialId, locator),
          bilingualAvailable
            ? getBilingualUnit(materialId, locator)
            : Promise.resolve({ locator, groups: [] as BilingualGroup[] }),
        ]);
        if (!cancelled) {
          setText(unitText.text);
          setBilingualGroups(bilingual.groups);
          // Translation disclosure is intentionally session-local and resets
          // closed whenever a unit or material is opened.
          setExpandedGroups(new Set());
        }
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
  }, [bilingualAvailable, materialId, locator, t]);

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

  const richAnnotations = contentFormat === "markdown" || bilingualGroups.length > 0;

  useEffect(() => {
    const article = articleRef.current;
    if (!article || !richAnnotations || loading || error) return;
    let cancelled = false;
    let annotator: { destroy: () => void } | null = null;

    void import("@recogito/text-annotator").then((module) => {
      if (cancelled) return;
      textSelectorToolsRef.current = {
        rangeToSelector: module.rangeToSelector,
        getQuoteContext: module.getQuoteContext,
      };
      const instance = module.createTextAnnotator(article, {
        annotatingEnabled: false,
        renderer: "SPANS",
        style: (annotation) => {
          const properties = annotation.properties as
            | { annotationId?: string; color?: string; kind?: string }
            | undefined;
          const color = COLOR_INK[properties?.color ?? ""] ?? COLOR_INK.yellow;
          if (properties?.kind === "underline") {
            return {
              fill: "transparent",
              underlineColor: `rgb(${color})`,
              underlineThickness: 2,
            };
          }
          return {
            fill: `rgb(${color})`,
            fillOpacity:
              properties?.annotationId === highlightedAnnotationId ? 0.8 : 0.55,
          };
        },
      });
      annotator = instance;
      const rows = annotations
        .filter((annotation) => annotation.locator === locator)
        .map((annotation) =>
          toRecogitoTextAnnotation(
            annotation,
            article.textContent ?? "",
          ),
        )
        .filter((annotation) => annotation !== null);
      instance.setAnnotations(rows);
      instance.on("clickAnnotation", (selected) => {
        const id = selected.id;
        const annotation = annotations.find((row) => row.annotation_id === id);
        if (annotation) onAnnotationClick?.(annotation);
      });
      if (highlightedAnnotationId) {
        instance.scrollIntoView(highlightedAnnotationId, containerRef.current ?? article);
      }
    });

    return () => {
      cancelled = true;
      annotator?.destroy();
      textSelectorToolsRef.current = null;
    };
  }, [
    annotations,
    bilingualGroups,
    contentFormat,
    error,
    highlightedAnnotationId,
    loading,
    locator,
    onAnnotationClick,
    richAnnotations,
    text,
  ]);

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
    const tools = textSelectorToolsRef.current;
    const selector =
      richAnnotations && tools && articleRef.current
        ? tools.rangeToSelector(range, articleRef.current)
        : null;
    const quote = selector?.quote || cleanQuote(selection.toString());
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
      selectors:
        selector && selector.quote.length <= 2000 && articleRef.current
          ? [
              {
                type: "TextQuoteSelector",
                exact: selector.quote,
                ...tools?.getQuoteContext(range, articleRef.current),
              },
              {
                type: "TextPositionSelector",
                start: selector.start,
                end: selector.end,
              },
            ]
          : [],
      anchor: last
        ? { x: last.left + last.width / 2, y: last.top }
        : { x: 0, y: 0 },
    });
  }, [locator, onSelection, richAnnotations]);

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
          {bilingualGroups.some((group) => group.translation_markdown.trim()) ? (
            <button
              type="button"
              onClick={() =>
                setExpandedGroups((current) =>
                  current.size
                    ? new Set()
                    : new Set(
                        bilingualGroups
                          .filter((group) => group.translation_markdown.trim())
                          .map((group) => group.group_id),
                      ),
                )
              }
              className="mr-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              {expandedGroups.size ? t("Collapse all Chinese") : t("Expand all Chinese")}
            </button>
          ) : null}
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
            ref={articleRef}
            className={`mx-auto leading-[1.75] selection:bg-[var(--primary)]/20 ${serif ? "font-serif" : "font-sans"}`}
            style={{
              maxWidth: `${lineWidth}ch`,
              fontSize: `${fontSize}px`,
              color: readerTheme === "auto" ? "var(--foreground)" : "inherit",
            }}
          >
            {bilingualGroups.length ? (
              <div className="space-y-5">
                {bilingualGroups.map((group) => (
                  <section key={group.group_id} data-bilingual-group={group.group_id}>
                    <MarkdownRenderer
                      content={group.source_markdown}
                      variant="prose"
                      allowHtml={false}
                    />
                    {group.translation_markdown.trim() ? (
                      <details
                        className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2"
                        open={expandedGroups.has(group.group_id)}
                        onToggle={(event) => {
                          const open = event.currentTarget.open;
                          setExpandedGroups((current) => {
                            const next = new Set(current);
                            if (open) next.add(group.group_id);
                            else next.delete(group.group_id);
                            return next;
                          });
                        }}
                      >
                        <summary
                          className="cursor-pointer text-xs font-medium text-[var(--primary)]"
                          onClick={(event) => {
                            // Keep the disclosure controlled by React. Native
                            // toggling can be suppressed inside the annotator's
                            // rich-text surface in embedded browsers.
                            event.preventDefault();
                            setExpandedGroups((current) => {
                              const next = new Set(current);
                              if (next.has(group.group_id)) {
                                next.delete(group.group_id);
                              } else {
                                next.add(group.group_id);
                              }
                              return next;
                            });
                          }}
                        >
                          {t("Show Chinese")}
                          {group.low_confidence ? (
                            <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-300">
                              {t("Check alignment")}
                            </span>
                          ) : null}
                        </summary>
                        <MarkdownRenderer
                          content={group.translation_markdown}
                          className="mt-2"
                          variant="prose"
                          allowHtml={false}
                        />
                      </details>
                    ) : null}
                  </section>
                ))}
              </div>
            ) : contentFormat === "markdown" ? (
              <MarkdownRenderer
                content={text}
                variant="prose"
                allowHtml={false}
              />
            ) : runs.length === 0 ? (
              <span className="text-[var(--muted-foreground)]">
                {t("This section has no extractable text.")}
              </span>
            ) : (
              <div className="whitespace-pre-wrap">{runs.map((run, index) =>
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
              )}</div>
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
