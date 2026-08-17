"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AudioLines,
  BookOpen,
  ChevronDown,
  CircleAlert,
  Languages,
  Loader2,
  BookPlus,
  RotateCw,
  Upload,
  Volume2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  chineseRevealClassName,
  nextDictionarySheetExpanded,
  positionDictionaryPopover,
  type DictionaryAnchorRect,
} from "@/lib/dictionary-ui";
import {
  immersiveReadingApi,
  type DictionaryResult,
  type DictionaryStatus,
} from "@/lib/immersive-reading-api";
import {
  subscribePronunciationState,
  type PronunciationPlaybackState,
  type WordPronunciationAccent,
} from "@/lib/word-pronunciation";
import {
  useResponsiveLayout,
  useDynamicViewportHeight,
} from "@/hooks/useResponsiveLayout";

type DictMode = "dictionary" | "translate";

function OfflineDictionarySetup() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<DictionaryStatus | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let stopped = false;
    void immersiveReadingApi
      .dictionaryStatus()
      .then((next) => {
        if (!stopped) setStatus(next);
      })
      .catch(() => undefined);
    return () => {
      stopped = true;
    };
  }, []);

  if (!status || status.installed) return null;

  const importFile = async (file: File) => {
    setImporting(true);
    setError("");
    try {
      const result = await immersiveReadingApi.importDictionaryCsv(file);
      setStatus({ ...status, installed: true, entries: result.entries, error: "" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-[var(--border)] p-3">
      <div className="flex items-center gap-2 text-xs font-medium text-[var(--foreground)]">
        <Upload size={13} />
        {t("Offline dictionary")}
        {status.version && (
          <span className="ml-2 rounded border border-[var(--border)] bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
            v{status.version}
          </span>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
      {status.import_progress !== null && status.import_progress !== undefined && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]">
          <div
            className="h-full bg-[var(--primary)] transition-all duration-300"
            style={{ width: `${Math.max(0, Math.min(100, status.import_progress * 100))}%` }}
          />
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void importFile(file);
        }}
      />
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={importing}
        className="mt-2 inline-flex min-h-[30px] items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
      >
        {importing && <Loader2 className="size-3 animate-spin" />}
        {importing ? t("Importing...") : t("Import ECDICT CSV")}
      </button>
    </div>
  );
}

/** Attach a click-outside listener that fires only after a short delay so
 *  the gesture that opened the sheet doesn't immediately close it. */
function useClickOutside(
  ref: React.RefObject<HTMLElement | null>,
  handler: () => void,
) {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) handler();
    };
    const timer = window.setTimeout(() => {
      document.addEventListener("click", onClick, true);
    }, 150);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("click", onClick, true);
    };
  }, [ref, handler]);
}

export interface DictionaryPanelProps {
  word: string;
  anchor: DictionaryAnchorRect;
  loading: boolean;
  result: DictionaryResult | null;
  error?: string | null;
  initialMode?: DictMode;
  onLookup: () => void;
  onTranslate: () => void;
  onClose: () => void;
  onModeChange?: (mode: DictMode) => void;
  /** Optional "Save to vocabulary" action (immersive reading page). */
  onSaveToVocabulary?: () => void;
  /** Disables the save action while a save request is in flight. */
  saveBusy?: boolean;
  /** Optional browser/Web Speech pronunciation controls. */
  onPronounce?: (accent: WordPronunciationAccent) => void;
}

/* ------------------------------------------------------------------ */
/*  Shared content fragments                                            */
/* ------------------------------------------------------------------ */

function CompactDefinition({ result }: { result: DictionaryResult }) {
  const { t } = useTranslation();
  const [revealChinese, setRevealChinese] = useState(false);
  const primary =
    result.definitions.find((d) => d.context_match) ?? result.definitions[0];
  const primaryChinese = primary?.chinese;
  const globalChinese = result.chinese;
  const shouldShowPrimaryChinese = !!normalizeChineseText(primaryChinese);
  const shouldShowGlobalChinese =
    !!normalizeChineseText(globalChinese) &&
    normalizeChineseText(primaryChinese) !== normalizeChineseText(globalChinese);

  return (
    <div className="space-y-1.5">
      {result.context_note && (
        <p className="text-xs italic leading-relaxed text-[var(--muted-foreground)]">
          {result.context_note}
        </p>
      )}
      {primary && (
      <div>
        <div className="mb-0.5 flex items-center gap-2">
          <span className="text-xs italic text-[var(--muted-foreground)]">
            {primary.part_of_speech}
          </span>
          {primary.context_match && (
            <span className="rounded bg-[var(--primary)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--primary-foreground)]">
              {t("In context")}
            </span>
          )}
        </div>
        <p className="text-sm leading-relaxed text-[var(--foreground)]">
          {primary.definition}
        </p>
        {shouldShowPrimaryChinese && (
          <button
            type="button"
            onClick={() => setRevealChinese(true)}
            aria-expanded={revealChinese}
            title={revealChinese ? undefined : t("Tap to reveal")}
            className={chineseRevealClassName(revealChinese)}
          >
            {primaryChinese}
          </button>
        )}
      </div>
      )}
      {shouldShowGlobalChinese && (
        <button
          type="button"
          onClick={() => setRevealChinese(true)}
          aria-expanded={revealChinese}
          title={revealChinese ? undefined : t("Tap to reveal")}
          className={chineseRevealClassName(revealChinese)}
        >
          {result.chinese}
        </button>
      )}
    </div>
  );
}

function FullDefinitions({ result }: { result: DictionaryResult }) {
  const { t } = useTranslation();
  const [revealChinese, setRevealChinese] = useState(false);
  const seenDefinitionChinese = new Set<string>();
  const hasChinese = !!result.chinese || result.definitions.some((d) => d.chinese);
  const globalChinese = normalizeChineseText(result.chinese);

  return (
    <div className="space-y-3">
      {result.context_note && (
        <p className="text-xs italic leading-relaxed text-[var(--muted-foreground)]">
          {result.context_note}
        </p>
      )}
      {hasChinese && (
        <div className="flex justify-end">
          <button
            onClick={() => setRevealChinese((v) => !v)}
            title={revealChinese ? t("Hide Chinese") : t("Show Chinese")}
            className="inline-flex min-h-[32px] items-center gap-1 rounded-md px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] active:bg-[var(--muted)]"
          >
            <Languages size={12} />
            {revealChinese ? t("Hide Chinese") : t("Show Chinese")}
          </button>
        </div>
      )}
      {globalChinese && (
        <button
          type="button"
          onClick={() => setRevealChinese(true)}
          aria-expanded={revealChinese}
          className={chineseRevealClassName(revealChinese)}
        >
          {result.chinese}
        </button>
      )}
      {result.definitions.map((def, i) => (
        <div
          key={i}
          className={
            def.context_match
              ? "rounded-lg border border-[var(--primary)]/30 bg-[var(--primary)]/5 p-2.5"
              : ""
          }
        >
          <div className="mb-0.5 flex items-center gap-2">
            <span className="text-xs italic text-[var(--muted-foreground)]">
              {def.part_of_speech}
            </span>
            {def.context_match && (
              <span className="rounded bg-[var(--primary)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--primary-foreground)]">
                {t("In context")}
              </span>
            )}
          </div>
          <p className="text-sm leading-relaxed text-[var(--foreground)]">
            {def.definition}
          </p>
          {(() => {
            const definitionChinese = normalizeChineseText(def.chinese);
            if (!definitionChinese) return null;
            if (definitionChinese === globalChinese) return null;
            if (seenDefinitionChinese.has(definitionChinese)) return null;
            seenDefinitionChinese.add(definitionChinese);
            return (
              <button
                type="button"
                onClick={() => setRevealChinese(true)}
                aria-expanded={revealChinese}
                title={revealChinese ? undefined : t("Tap to reveal")}
                className={chineseRevealClassName(revealChinese)}
              >
                {definitionChinese}
              </button>
            );
          })()}
          {def.example && (
            <p className="mt-1 text-xs italic text-[var(--muted-foreground)]">
              &ldquo;{def.example}&rdquo;
            </p>
          )}
          {def.synonyms.length > 0 && (
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("Synonyms")}: {def.synonyms.join(", ")}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared panel body                                                   */
/* ------------------------------------------------------------------ */

interface ContentProps {
  word: string;
  loading: boolean;
  result: DictionaryResult | null;
  error?: string | null;
  mode: DictMode;
  expanded: boolean;
  onModeChange: (mode: DictMode) => void;
  onLookup: () => void;
  onTranslate: () => void;
  onExpand: () => void;
  onClose: () => void;
  onRetry?: () => void;
  onSaveToVocabulary?: () => void;
  saveBusy?: boolean;
  onPronounce?: (accent: WordPronunciationAccent) => void;
}

function normalizeChineseText(value: string | null | undefined): string {
  return (value || "").trim().replace(/\s+/g, " ");
}

function PanelContent({
  word,
  loading,
  result,
  error,
  mode,
  expanded,
  onModeChange,
  onLookup,
  onTranslate,
  onExpand,
  onClose,
  onRetry,
  onSaveToVocabulary,
  saveBusy,
  onPronounce,
}: ContentProps) {
  const { t } = useTranslation();
  const [audioState, setAudioState] = useState<PronunciationPlaybackState>({
    isPlaying: false,
    word: null,
    accent: null,
  });

  useEffect(() => {
    return subscribePronunciationState(setAudioState);
  }, []);

  const isCurrentWordPlaying =
    audioState.isPlaying &&
    audioState.word?.toLowerCase() === word.trim().toLowerCase();
  const isPlayingUS = isCurrentWordPlaying && audioState.accent === "en-US";
  const isPlayingUK = isCurrentWordPlaying && audioState.accent === "en-GB";

  const isDictResult =
    !!result && (result.definitions.length > 0 || !!result.chinese);
  const isTranslateResult =
    !!result && result.definitions.length === 0 && !!result.context_note;
  const hasResult =
    !!result &&
    (result.definitions.length > 0 || !!result.chinese || !!result.context_note);
  const showExpandButton =
    !expanded && isDictResult && result!.definitions.length > 1;

  const handleModeChange = (next: DictMode) => {
    if (next === mode) return;
    onModeChange(next);
    if (next === "dictionary" && !isDictResult) onLookup();
    if (next === "translate" && !isTranslateResult) onTranslate();
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <BookOpen size={15} className="shrink-0 text-[var(--primary)]" />
          <span className="truncate text-sm font-medium text-[var(--foreground)]">
            {word}
          </span>
          {result?.phonetic && (
            <span className="shrink-0 font-mono text-xs text-[var(--muted-foreground)]">
              /{result.phonetic}/
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {onPronounce && (
            <>
              <button
                type="button"
                onClick={() => onPronounce("en-US")}
                title={t("Play US pronunciation (P)")}
                aria-label={t("Play US pronunciation (P)")}
                className={`inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs transition ${
                  isPlayingUS
                    ? "bg-[var(--primary)]/15 text-[var(--primary)] ring-1 ring-[var(--primary)]/40 animate-pulse"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                }`}
              >
                {isPlayingUS ? <AudioLines size={14} /> : <Volume2 size={14} />}
                <span className="text-[10px] font-semibold">{t("US")}</span>
              </button>
              <button
                type="button"
                onClick={() => onPronounce("en-GB")}
                title={t("Play UK pronunciation (Shift+P)")}
                aria-label={t("Play UK pronunciation (Shift+P)")}
                className={`inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs transition ${
                  isPlayingUK
                    ? "bg-[var(--primary)]/15 text-[var(--primary)] ring-1 ring-[var(--primary)]/40 animate-pulse"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                }`}
              >
                {isPlayingUK ? <AudioLines size={14} /> : <Volume2 size={14} />}
                <span className="text-[10px] font-semibold">{t("UK")}</span>
              </button>
            </>
          )}
          <button
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Mode tabs */}
      <div className="flex shrink-0 gap-1 p-2">
        <button
          onClick={() => handleModeChange("dictionary")}
          className={
            "flex flex-1 min-h-[36px] items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition " +
            (mode === "dictionary"
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]")
          }
        >
          <BookOpen size={13} />
          {t("Dictionary")}
        </button>
        <button
          onClick={() => handleModeChange("translate")}
          className={
            "flex flex-1 min-h-[36px] items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition " +
            (mode === "translate"
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]")
          }
        >
          <Languages size={13} />
          {t("Translate")}
        </button>
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-2">
        {loading && (
          <div className="flex items-center gap-2 py-6 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="size-4 animate-spin" />
            {t("Thinking...")}
          </div>
        )}

        {!loading && error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-500/25 bg-red-500/8 p-3 text-sm text-red-500">
            <CircleAlert size={15} className="mt-0.5 shrink-0" />
            <div className="flex-1">
              <span>{error}</span>
              {onRetry && (
                <button
                  onClick={mode === "translate" ? onTranslate : onLookup}
                  className="mt-1.5 inline-flex min-h-[28px] items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-red-500 hover:bg-red-500/10"
                >
                  <RotateCw size={12} />
                  {t("Retry")}
                </button>
              )}
            </div>
          </div>
        )}

        {!loading && mode === "dictionary" && <OfflineDictionarySetup />}

        {!loading && !error && mode === "dictionary" && isDictResult && (
          expanded ? (
            <FullDefinitions result={result!} />
          ) : (
            <CompactDefinition result={result!} />
          )
        )}

        {!loading && !error && mode === "translate" && isTranslateResult && (
          <p className="text-sm leading-relaxed text-[var(--foreground)]">
            {result!.context_note}
          </p>
        )}

        {!loading && !error && !hasResult && (
          <p className="py-4 text-center text-xs text-[var(--muted-foreground)]">
            {t("No result")}
          </p>
        )}
      </div>

      {/* Footer: expand + save */}
      <div className="shrink-0 border-t border-[var(--border)] px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          {showExpandButton ? (
            <button
              onClick={onExpand}
              className="inline-flex min-h-[32px] items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-[var(--primary)] hover:bg-[var(--muted)]"
            >
              <ChevronDown size={13} />
              {t("Expand")}
            </button>
          ) : (
            <span />
          )}
          {onSaveToVocabulary && (
            <button
              type="button"
              onClick={onSaveToVocabulary}
              disabled={saveBusy}
              className="inline-flex min-h-[32px] items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-60"
            >
              {saveBusy ? <Loader2 className="animate-spin" size={13} /> : <BookPlus size={13} />}
              {saveBusy ? t("Saving…") : t("Save to vocabulary")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Mobile: bottom sheet                                                */
/* ------------------------------------------------------------------ */

function MobileSheet(props: DictionaryPanelProps) {
  const { onClose } = props;
  const { t } = useTranslation();
  const vh = useDynamicViewportHeight();
  const [expanded, setExpanded] = useState(false);
  const dragStartYRef = useRef<number | null>(null);
  const [dragDeltaY, setDragDeltaY] = useState(0);

  const collapsedH = Math.round((vh || 600) * 0.48);
  const expandedH = Math.round((vh || 600) * 0.88);
  const height = expanded ? expandedH : collapsedH;

  const finishDrag = () => {
    dragStartYRef.current = null;
    setDragDeltaY(0);
  };

  const handleDragStart = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStartYRef.current = event.clientY;
    setDragDeltaY(0);
  };

  const handleDragMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const startY = dragStartYRef.current;
    if (startY === null) return;
    const delta = event.clientY - startY;
    setDragDeltaY(delta);
    const next = nextDictionarySheetExpanded(expanded, delta, vh || window.innerHeight);
    if (next !== expanded) {
      setExpanded(next);
      dragStartYRef.current = event.clientY;
      setDragDeltaY(0);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <>
      <button
        type="button"
        aria-label={t("Close dictionary")}
        onClick={onClose}
        className="fixed inset-0 z-[199] cursor-default bg-black/10"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={props.word}
        className="fixed bottom-0 left-0 right-0 z-[200] flex flex-col overflow-hidden rounded-t-2xl border border-[var(--border)] bg-[var(--background)] shadow-2xl"
        style={{
          height,
          transform: dragDeltaY ? `translateY(${Math.max(-24, dragDeltaY)}px)` : undefined,
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
          transition: "height 250ms cubic-bezier(0.22, 1, 0.36, 1)",
          animation: "dt-sheet-up 250ms cubic-bezier(0.22, 1, 0.36, 1)",
          pointerEvents: "auto",
        }}
      >
      {/* Drag handle */}
      <div
        className="flex h-8 shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
        role="separator"
        aria-label={t("Drag to expand dictionary")}
        aria-orientation="horizontal"
        onPointerDown={handleDragStart}
        onPointerMove={handleDragMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onLostPointerCapture={finishDrag}
      >
        <div className="h-1 w-9 rounded-full bg-[var(--muted-foreground)]/30" />
      </div>
      <div className="min-h-0 flex-1">
        <PanelContent
          word={props.word}
          loading={props.loading}
          result={props.result}
          error={props.error}
          mode={props.initialMode ?? "dictionary"}
          expanded={expanded}
          onModeChange={props.onModeChange ?? (() => {})}
          onLookup={props.onLookup}
          onTranslate={props.onTranslate}
          onExpand={() => setExpanded(true)}
          onClose={onClose}
          onRetry={() => {}}
          onSaveToVocabulary={props.onSaveToVocabulary}
          saveBusy={props.saveBusy}
          onPronounce={props.onPronounce}
        />
      </div>
      </div>
    </>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/*  Desktop: anchored card or expanded right sidebar                    */
/* ------------------------------------------------------------------ */

function DesktopPanel(props: DictionaryPanelProps) {
  const { anchor, onClose } = props;
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<ReturnType<
    typeof positionDictionaryPopover
  > | null>(null);

  useLayoutEffect(() => {
    if (expanded) return;
    const update = () => {
      const rect = cardRef.current?.getBoundingClientRect();
      if (!rect) return;
      setPosition(
        positionDictionaryPopover(
          anchor,
          { width: rect.width, height: rect.height },
          { width: window.innerWidth, height: window.innerHeight },
        ),
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchor, expanded, props.loading, props.result]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const content = (
    <PanelContent
      word={props.word}
      loading={props.loading}
      result={props.result}
      error={props.error}
      mode={props.initialMode ?? "dictionary"}
      expanded={expanded}
      onModeChange={props.onModeChange ?? (() => {})}
      onLookup={props.onLookup}
      onTranslate={props.onTranslate}
      onExpand={() => setExpanded(true)}
      onClose={onClose}
      onRetry={() => {}}
      onSaveToVocabulary={props.onSaveToVocabulary}
      saveBusy={props.saveBusy}
      onPronounce={props.onPronounce}
    />
  );

  if (expanded) {
    return createPortal(
      <div
        className="fixed inset-0 z-[200]"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <div
          className="absolute bottom-0 right-0 top-0 flex w-[min(380px,calc(100vw-16px))] flex-col border-l border-[var(--border)] bg-[var(--background)] shadow-2xl"
          style={{ animation: "dt-sidebar-in 220ms cubic-bezier(0.16,1,0.3,1)" }}
        >
          {content}
        </div>
      </div>,
      document.body,
    );
  }

  return createPortal(
    <div
      ref={cardRef}
      className="fixed z-[200] w-[min(360px,calc(100vw-16px))]"
      style={{
        left: position?.left ?? 8,
        top: position?.top ?? 8,
        visibility: position ? "visible" : "hidden",
        maxHeight: "min(60vh, 460px)",
        animation: "dt-pop-in 180ms cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      <div className="flex max-h-[min(60vh,460px)] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
        {content}
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/*  Public component                                                    */
/* ------------------------------------------------------------------ */

export default function DictionaryPanel(props: DictionaryPanelProps) {
  const layout = useResponsiveLayout();
  const [mode, setMode] = useState<DictMode>(props.initialMode ?? "dictionary");

  const enhancedProps: DictionaryPanelProps = {
    ...props,
    initialMode: mode,
    onModeChange: setMode as (mode: DictMode) => void,
  };

  if (layout === "mobile") return <MobileSheet {...enhancedProps} />;
  return <DesktopPanel {...enhancedProps} />;
}
