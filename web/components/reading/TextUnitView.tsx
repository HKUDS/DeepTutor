"use client";

import { browserStorage } from "@/shared/storage";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ALargeSmall,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  Rows3,
  SunMoon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import type { AnnotationItem, UnitKind } from "@/lib/reading-api";
import { getUnitText } from "@/lib/reading-api";
import {
  DEFAULT_FONT_SIZE,
  DEFAULT_LINE_WIDTH,
  DEFAULT_READER_DISPLAY_PREFERENCES,
  MAX_FONT_SIZE,
  MAX_LINE_WIDTH,
  MIN_FONT_SIZE,
  MIN_LINE_WIDTH,
  normaliseReaderDisplayPreferences,
  readerDisplayShortcut,
  type ReaderTheme,
} from "@/lib/reading-display-preferences";
import {
  activeReaderHeading,
  extractReaderHeadings,
  readerLinesWithHeadings,
  type ReaderHeading,
} from "@/lib/reading-outline";
import { cleanQuote } from "@/lib/reading-selection";
import { MarkdownLine } from "@/lib/reading-inline-markdown";
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
const LINE_WIDTH_STEPS = [48, 64, 84, 104];

export interface TextUnitViewProps {
  materialId: string;
  unit: UnitKind;
  unitCount: number;
  contentFormat?: "plain_text" | "web_markdown";
  annotations: AnnotationItem[];
  jump: JumpRequest | null;
  highlightedAnnotationId?: string | null;
  onSelection: (payload: SelectionPayload | null) => void;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  onVisibleLocatorChange?: (locator: number) => void;
  onHeadingsChange?: (headings: ReaderHeading[]) => void;
  onActiveHeadingChange?: (headingId: string | null) => void;
  headingJump?: { id: string; nonce: number } | null;
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
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
  onHeadingsChange,
  onActiveHeadingChange,
  headingJump,
}: TextUnitViewProps) {
  const { t } = useTranslation();
  const readerRootRef = useRef<HTMLDivElement | null>(null);
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState(DEFAULT_FONT_SIZE);
  const [lineWidth, setLineWidth] = useState(DEFAULT_LINE_WIDTH);
  const [serif, setSerif] = useState(true);
  const [readerTheme, setReaderTheme] = useState<ReaderTheme>("auto");
  const isWebMarkdown = contentFormat === "web_markdown";
  // Sepia and Night are whole-surface paper: a sheet drawn on top of them
  // would be a second, differently coloured page inside the first.
  const paperSheet = readerTheme === "auto";

  useEffect(() => {
    try {
      const value = normaliseReaderDisplayPreferences(
        JSON.parse(browserStorage.readRaw("local", READER_PREFS_KEY) || "{}"),
      );
      setFontSize(value.fontSize);
      setLineWidth(value.lineWidth);
      setSerif(value.serif);
      setReaderTheme(value.readerTheme);
    } catch {
      // Invalid or unavailable local storage falls back to readable defaults.
    }
  }, []);

  const updatePreferences = useCallback(
    (
      next: Partial<{
        fontSize: number;
        lineWidth: number;
        serif: boolean;
        readerTheme: ReaderTheme;
      }>,
    ) => {
      const merged = { fontSize, lineWidth, serif, readerTheme, ...next };
      setFontSize(merged.fontSize);
      setLineWidth(merged.lineWidth);
      setSerif(merged.serif);
      setReaderTheme(merged.readerTheme);
      try {
        browserStorage.writeRaw(
          "local",
          READER_PREFS_KEY,
          JSON.stringify(merged),
        );
      } catch {
        // Preferences still apply for the current session.
      }
    },
    [fontSize, lineWidth, readerTheme, serif],
  );

  const changeFontSize = useCallback(
    (next: number) => {
      updatePreferences({
        fontSize: Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, next)),
      });
    },
    [updatePreferences],
  );

  const resetPreferences = useCallback(() => {
    updatePreferences(DEFAULT_READER_DISPLAY_PREFERENCES);
  }, [updatePreferences]);

  const cycleLineWidth = useCallback(() => {
    const nextWidth =
      LINE_WIDTH_STEPS.find((width) => width > lineWidth) ?? MIN_LINE_WIDTH;
    updatePreferences({ lineWidth: nextWidth });
  }, [lineWidth, updatePreferences]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const root = readerRootRef.current;
      const action = readerDisplayShortcut({
        key: event.key,
        modifier: event.metaKey || event.ctrlKey,
        readerHovered: root?.matches(":hover") ?? false,
        readerFocused: Boolean(root && root.contains(document.activeElement)),
      });
      if (!action) return;
      event.preventDefault();
      if (action === "increase") changeFontSize(fontSize + 1);
      if (action === "decrease") changeFontSize(fontSize - 1);
      if (action === "reset") resetPreferences();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changeFontSize, fontSize, resetPreferences]);
  const headingsChangeRef = useRef(onHeadingsChange);
  const activeHeadingChangeRef = useRef(onActiveHeadingChange);

  useEffect(() => {
    headingsChangeRef.current = onHeadingsChange;
    activeHeadingChangeRef.current = onActiveHeadingChange;
  }, [onActiveHeadingChange, onHeadingsChange]);

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

  useEffect(() => {
    const article = articleRef.current;
    if (!article || loading || error) return;
    let cancelled = false;
    let annotator: { destroy: () => void } | null = null;

    void import("@recogito/text-annotator")
      .then((module) => {
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
            const color =
              COLOR_INK[properties?.color ?? ""] ?? COLOR_INK.yellow;
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
                properties?.annotationId === highlightedAnnotationId
                  ? 0.8
                  : 0.55,
            };
          },
        });
        annotator = instance;
        const rows = annotations
          .filter((annotation) => annotation.locator === locator)
          .map((annotation) =>
            toRecogitoTextAnnotation(annotation, article.textContent ?? ""),
          )
          .filter((annotation) => annotation !== null);
        instance.setAnnotations(rows);
        instance.on("clickAnnotation", (selected) => {
          const id = selected.id;
          const annotation = annotations.find(
            (row) => row.annotation_id === id,
          );
          if (annotation) onAnnotationClick?.(annotation);
        });
        if (highlightedAnnotationId) {
          instance.scrollIntoView(
            highlightedAnnotationId,
            containerRef.current ?? article,
          );
        }
      })
      .catch(() => {
        // The text remains readable and selection falls back to legacy quotes.
        if (!cancelled) textSelectorToolsRef.current = null;
      });

    return () => {
      cancelled = true;
      annotator?.destroy();
      textSelectorToolsRef.current = null;
    };
  }, [
    annotations,
    error,
    highlightedAnnotationId,
    loading,
    locator,
    onAnnotationClick,
    text,
  ]);

  const pageHeadings = useMemo(
    () => extractReaderHeadings([text], locator),
    [locator, text],
  );

  useEffect(() => {
    if (!isWebMarkdown) return;
    const article = articleRef.current;
    if (!article || loading || error) return;
    article
      .querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6")
      .forEach((element, index) => {
        const heading = pageHeadings[index];
        if (!heading) return;
        element.id = heading.id;
        element.dataset.readerHeadingId = heading.id;
      });
  }, [error, isWebMarkdown, loading, pageHeadings]);

  useEffect(() => {
    headingsChangeRef.current?.(pageHeadings);
    return () => headingsChangeRef.current?.([]);
  }, [pageHeadings]);

  useEffect(() => {
    if (!headingJump) return;
    const container = containerRef.current;
    const element = container?.querySelector<HTMLElement>(
      `[data-reader-heading-id="${CSS.escape(headingJump.id)}"]`,
    );
    if (!container || !element) return;
    const containerRect = container.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    container.scrollTo({
      top: Math.max(
        0,
        container.scrollTop + elementRect.top - containerRect.top - 24,
      ),
    });
    activeHeadingChangeRef.current?.(headingJump.id);
  }, [headingJump]);

  const handleContainerScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container || pageHeadings.length === 0) return;
    const containerRect = container.getBoundingClientRect();
    activeHeadingChangeRef.current?.(
      activeReaderHeading(pageHeadings, (heading) => {
        const element = container.querySelector<HTMLElement>(
          `[data-reader-heading-id="${CSS.escape(heading.id)}"]`,
        );
        if (!element) return null;
        return element.getBoundingClientRect().top - containerRect.top;
      }),
    );
  }, [pageHeadings]);

  const handlePointerUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      onSelection(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (
      !text.trim() ||
      !articleRef.current?.contains(range.commonAncestorContainer)
    ) {
      onSelection(null);
      return;
    }
    const tools = textSelectorToolsRef.current;
    const selector = tools?.rangeToSelector(range, articleRef.current);
    const quote =
      selector && selector.quote.length <= 2000
        ? selector.quote
        : cleanQuote(selection.toString());
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
        selector && selector.quote === quote
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
  }, [locator, onSelection, text]);

  const canPrev = locator > 1;
  const canNext = locator < unitCount;

  return (
    <div
      ref={readerRootRef}
      tabIndex={-1}
      onPointerDown={() =>
        readerRootRef.current?.focus({ preventScroll: true })
      }
      className="flex h-full flex-col"
      style={
        readerTheme === "sepia"
          ? { background: "#f4ecd8", color: "#473c2c" }
          : readerTheme === "night"
            ? { background: "#16181d", color: "#e8e5df" }
            // A desk, not a page — the page is the article below, the same
            // relationship a scrolled PDF already has between its grey field
            // and the white sheets on it. Sepia and Night are whole-surface
            // paper by design, so they keep painting edge to edge.
            : { background: "var(--secondary)" }
      }
    >
      {/* Display controls on the left, position on the right.

          This row used to also print "106%" and "84ch" between its buttons and
          repeat the reader's position — "Section 1 of 74" — 44px under the
          header's own "Section 1/74", in a monospace font. Three readouts of
          state nobody had asked to see made a reading surface look like a
          debug panel, and one of them said the same thing twice.

          Each value is now where it belongs: the size and width live in the
          label of the control that changes them (so a screen reader announces
          the new value on press, which the silent spans never did), and the
          position is the header's to state, since that is the one line that is
          there in every render mode. What is left here is what you can *do*. */}
      <div className="flex items-center justify-between gap-2 overflow-x-auto border-b border-[var(--border)] px-2 py-2 sm:px-3">
        <div className="flex shrink-0 items-center gap-0.5">
          <PreferenceButton
            label={t("Smaller text ({{percent}}%)", {
              percent: Math.round((fontSize / 16) * 100),
            })}
            icon={Minus}
            disabled={fontSize <= MIN_FONT_SIZE}
            onClick={() => changeFontSize(fontSize - 1)}
          />
          <PreferenceButton
            label={t("Larger text ({{percent}}%)", {
              percent: Math.round((fontSize / 16) * 100),
            })}
            icon={Plus}
            disabled={fontSize >= MAX_FONT_SIZE}
            onClick={() => changeFontSize(fontSize + 1)}
          />
          <PreferenceButton
            label={serif ? t("Use sans-serif font") : t("Use serif font")}
            icon={ALargeSmall}
            active={!serif}
            onClick={() => updatePreferences({ serif: !serif })}
          />
          <PreferenceButton
            label={t("Change line width ({{width}} characters)", {
              width: lineWidth,
            })}
            icon={Rows3}
            onClick={cycleLineWidth}
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
          <PreferenceButton
            label={t("Reset reading display")}
            icon={RotateCcw}
            onClick={resetPreferences}
          />
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <PreferenceButton
            label={t("Previous {{unit}}", { unit: t(unitLabel(unit)) })}
            icon={ChevronLeft}
            disabled={!canPrev}
            onClick={() => setLocator((current) => Math.max(1, current - 1))}
          />
          <PreferenceButton
            label={t("Next {{unit}}", { unit: t(unitLabel(unit)) })}
            icon={ChevronRight}
            disabled={!canNext}
            onClick={() =>
              setLocator((current) => Math.min(unitCount, current + 1))
            }
          />
        </div>
      </div>

      <div
        ref={containerRef}
        data-reader-unit={locator}
        onMouseUp={handlePointerUp}
        onScroll={handleContainerScroll}
        className="dt-reader-scroll flex-1 overflow-y-auto overscroll-contain px-5 py-6 sm:px-8"
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
            // The sheet. Text used to run edge to edge on the same white as
            // everything around it, so the chosen line width was invisible and
            // the reading column had no boundary to sit inside — four white
            // panes separated by hairlines. A PDF already reads as pages on a
            // desk; this gives the text modes the same surface.
            //
            // The edge is the border token rather than a black hairline
            // because the desk is not reliably darker than the sheet: of the
            // four palettes, Dark is the one whose --secondary sits above
            // --card. `--border` is defined against each palette's own
            // surfaces, so the boundary holds in all of them — and it is what
            // the mastery cards draw themselves with.
            className={`mx-auto leading-[1.75] selection:bg-[color-mix(in_srgb,var(--primary)_20%,transparent)] ${
              paperSheet
                ? "rounded-2xl border border-[var(--border)] bg-[var(--card)] px-6 py-8 shadow-[0_1px_3px_rgba(0,0,0,0.06),0_10px_30px_-16px_rgba(0,0,0,0.14)] sm:px-10 "
                : ""
            }${isWebMarkdown ? "" : "whitespace-pre-wrap "}${
              serif ? "font-serif" : "font-sans"
            }`}
            style={{
              // The sheet's padding is added on top of the line width, so
              // "84ch" stays 84 characters of text either way.
              maxWidth: paperSheet
                ? `calc(${lineWidth}ch + 5rem)`
                : `${lineWidth}ch`,
              fontSize: `${fontSize}px`,
              color: readerTheme === "auto" ? "var(--foreground)" : "inherit",
            }}
          >
            {!text.trim() ? (
              <span className="text-[var(--muted-foreground)]">
                {t("This section has no extractable text.")}
              </span>
            ) : isWebMarkdown ? (
              <RichMarkdownRenderer
                content={text}
                allowHtml={false}
                enableMath
                enableCode
                enableMermaid={false}
                enableImages
                variant="prose"
              />
            ) : (
              <TextWithHeadings text={text} headings={pageHeadings} />
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
  active = false,
  disabled = false,
  onClick,
}: {
  label: string;
  icon: typeof Minus;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg transition hover:bg-[var(--muted)] disabled:opacity-35 disabled:hover:bg-transparent ${
        active
          ? "text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={15} />
    </button>
  );
}

function TextWithHeadings({
  text,
  headings,
}: {
  text: string;
  headings: ReaderHeading[];
}) {
  const lines = useMemo(
    () => readerLinesWithHeadings(text, headings),
    [headings, text],
  );

  return (
    <>
      {lines.map((line, lineIndex) => {
        const key = `line-${lineIndex}`;
        if (line.heading) {
          const Heading = `h${line.heading.level}` as
            | "h1"
            | "h2"
            | "h3"
            | "h4"
            | "h5"
            | "h6";
          const titleOffset = line.text.indexOf(line.heading.title);
          const markerPrefix =
            titleOffset >= 0 ? line.text.slice(0, titleOffset) : "";
          const markerSuffix =
            titleOffset >= 0
              ? line.text.slice(titleOffset + line.heading.title.length)
              : "";
          return (
            <Fragment key={key}>
              {lineIndex > 0 && "\n"}
              <Heading
                id={line.heading.id}
                data-reader-heading-id={line.heading.id}
                className="mt-5 mb-2 font-serif text-[var(--foreground)] first:mt-0"
              >
                {markerPrefix && (
                  <span
                    aria-hidden="true"
                    className="inline-block size-0 overflow-hidden align-top text-[0px]"
                  >
                    {markerPrefix}
                  </span>
                )}
                {titleOffset >= 0 ? line.heading.title : line.text}
                {markerSuffix && (
                  <span
                    aria-hidden="true"
                    className="inline-block size-0 overflow-hidden align-top text-[0px]"
                  >
                    {markerSuffix}
                  </span>
                )}
              </Heading>
            </Fragment>
          );
        }
        return (
          <Fragment key={key}>
            {lineIndex > 0 && "\n"}
            {/* Fenced code stays completely literal — Markdown syntax
                inside a code block is content, not formatting. */}
            {line.fence ? line.text : <MarkdownLine text={line.text} />}
          </Fragment>
        );
      })}
    </>
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
