"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Crosshair,
  Download,
  FileText,
  List,
  Loader2,
  PanelRightClose,
  PanelRightOpen,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useReading } from "@/context/ReadingContext";
import {
  READER_ACTION_EVENT,
  READER_TURN_END_EVENT,
  type ReaderActionPayload,
} from "@/lib/reading-reader-action";
import { locatorFromHref } from "@/lib/reading-citations";
import {
  fetchExport,
  type AnnotationColor,
  type AnnotationItem,
} from "@/lib/reading-api";
import { AnnotationList } from "./AnnotationList";
import { AnnotationPopover } from "./AnnotationPopover";
import { MaterialPicker } from "./MaterialPicker";
import {
  PdfDocumentView,
  type JumpRequest,
  type SelectionPayload,
} from "./PdfDocumentView";
import { ReaderResizeHandle } from "./ReaderResizeHandle";
import { TextUnitView, unitLabel } from "./TextUnitView";

/** Event the reader dispatches to prefill the composer from a selection. */
export const READER_ASK_EVENT = "dt:reader-ask";
const AUTO_JUMP_KEY = "dt.reader.autoJump";

export interface ReaderPaneProps {
  onClose: () => void;
}

/**
 * The reading pane: document on the left of the chat, with its own annotations.
 *
 * Two behaviours are worth calling out because they were explicit product
 * decisions rather than defaults:
 *
 * * **Auto-jump is a user-owned toggle, not a rate limit.** The assistant may
 *   call `reader_goto` as often as it likes — once per passage it discusses is
 *   the intended usage. When the toggle is on, the view follows every call, so
 *   the reader watches the model read. When it is off, jumps are ignored and the
 *   citations in the answer remain clickable, so the user stays in control of
 *   their own scroll position. The preference persists across sessions.
 * * **Annotations are optimistic.** A highlight appears the moment it is drawn
 *   and is reconciled with the server's row when the write returns; a failed
 *   write removes it again and surfaces the error. Waiting for a round trip
 *   before showing ink makes highlighting feel broken.
 */
export function ReaderPane({ onClose }: ReaderPaneProps) {
  const { t } = useTranslation();
  // Document + annotations live in the provider (workspace layout), so they
  // survive the remount that sending the first message causes.
  const {
    material,
    annotations,
    loading: loadingMaterial,
    error: notice,
    openMaterial,
    closeMaterial,
    saveMark,
    removeMark,
    mergeMark,
    dismissError,
    setError,
    reportViewport,
  } = useReading();

  const [activeAnnotationId, setActiveAnnotationId] = useState<string | null>(
    null,
  );
  const [selection, setSelection] = useState<SelectionPayload | null>(null);
  const [jump, setJump] = useState<JumpRequest | null>(null);
  // `null` = follow the document: show the panel once there is something in it.
  // An empty panel is a whole column of nothing next to the page, which reads as
  // a layout bug rather than an affordance. An explicit true/false means the
  // user decided, and that wins from then on.
  const [annotationPanel, setAnnotationPanel] = useState<boolean | null>(null);
  const [showOutline, setShowOutline] = useState(false);
  const [autoJump, setAutoJump] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [currentLocator, setCurrentLocator] = useState(1);
  const nonceRef = useRef(0);

  // -- persisted auto-jump preference --------------------------------------

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(AUTO_JUMP_KEY);
      if (stored !== null) setAutoJump(stored === "1");
    } catch {
      // Private mode / storage disabled — keep the default.
    }
  }, []);

  const toggleAutoJump = useCallback(() => {
    setAutoJump((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(AUTO_JUMP_KEY, next ? "1" : "0");
      } catch {
        // Non-fatal: the toggle still works for this session.
      }
      return next;
    });
  }, []);

  // -- viewport reporting --------------------------------------------------

  const handleVisibleLocator = useCallback(
    (locator: number) => {
      setCurrentLocator(locator);
      reportViewport({ locator });
    },
    [reportViewport],
  );

  useEffect(() => {
    reportViewport({ selection: selection?.quote ?? "" });
  }, [selection, reportViewport]);

  // -- reader actions from the assistant -----------------------------------

  const requestJump = useCallback((locator: number, quote?: string) => {
    nonceRef.current += 1;
    setJump({ locator, quote, nonce: nonceRef.current });
  }, []);

  useEffect(() => {
    const onReaderAction = (event: Event) => {
      const detail = (event as CustomEvent<ReaderActionPayload>).detail;
      if (!detail || !material) return;
      // Ignore actions aimed at a document that is no longer open — a stale
      // event replayed from an earlier turn must not move the current view.
      if (detail.material_id && detail.material_id !== material.material_id)
        return;

      if (detail.reader_action === "annotate" && detail.annotation) {
        const incoming = detail.annotation as unknown as AnnotationItem;
        if (incoming.annotation_id) {
          mergeMark(incoming);
        }
      }
      if (!autoJump) return;
      const locator = Number(detail.locator ?? 0);
      if (locator >= 1) requestJump(locator, detail.quote || undefined);
    };
    window.addEventListener(READER_ACTION_EVENT, onReaderAction);
    return () =>
      window.removeEventListener(READER_ACTION_EVENT, onReaderAction);
  }, [material, autoJump, requestJump, mergeMark]);

  /**
   * Follow the answer when the model did not move the reader itself.
   *
   * `reader_goto` is the intended path and gives a highlighted quote; this is
   * the safety net for the turns where the model cites `[p.5]` in prose and
   * simply never calls it. Without it the reader sits on page 1 next to an
   * answer about page 5, which reads as broken no matter whose fault it is.
   *
   * Deliberately the FIRST citation of the LAST answer, and only when auto-jump
   * is on: it is the same promise the toggle makes — the view follows what the
   * assistant is talking about.
   */
  useEffect(() => {
    const onTurnEnd = (event: Event) => {
      const moved = (event as CustomEvent<{ moved?: boolean }>).detail?.moved;
      if (moved || !autoJump || !material) return;
      // One frame later: the final answer is still being committed to the DOM
      // as the turn closes.
      const timer = window.setTimeout(() => {
        const answers = document.querySelectorAll('[role="article"]');
        const last = answers[answers.length - 1];
        const anchor = last?.querySelector<HTMLAnchorElement>(
          'a[href^="#dt-locator-"]',
        );
        const locator = locatorFromHref(anchor?.getAttribute("href"));
        if (locator) requestJump(locator);
      }, 120);
      return () => window.clearTimeout(timer);
    };
    window.addEventListener(READER_TURN_END_EVENT, onTurnEnd);
    return () => window.removeEventListener(READER_TURN_END_EVENT, onTurnEnd);
  }, [autoJump, material, requestJump]);

  /**
   * Citation clicks in assistant prose, intercepted in the CAPTURE phase.
   *
   * It has to be capture, and it has to be here. The shared Markdown renderer
   * calls `preventDefault()` on *every* `#`-prefixed link before looking for an
   * element with that id (RichMarkdownRenderer's hash-link branch), and the chat
   * page's own delegated handler bails on `event.defaultPrevented`. A citation
   * would therefore be swallowed in the bubble phase and do nothing at all.
   * Capture runs before React dispatches any of that, and `stopPropagation`
   * keeps the renderer's hash handling from firing afterwards.
   */
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      // Leave modified clicks to the browser — a user opening a citation in a
      // new tab is asking for the link, not for the reader to move.
      if (event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
        return;
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest?.("a[href]") as HTMLAnchorElement | null;
      const locator = locatorFromHref(anchor?.getAttribute("href"));
      if (!locator) return;
      event.preventDefault();
      event.stopPropagation();
      requestJump(locator);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [requestJump]);

  // -- annotations ---------------------------------------------------------

  const commitSelection = useCallback(
    (
      kind: "highlight" | "underline" | "note",
      color: AnnotationColor,
      note = "",
    ) => {
      if (!selection || !material) return;
      const temporaryId = `pending-${Date.now()}-${Math.round(Math.random() * 1e6)}`;
      const now = Date.now() / 1000;
      void saveMark(
        {
          locator: selection.locator,
          kind: kind === "note" ? "highlight" : kind,
          color,
          quote: selection.quote,
          note,
          rects: selection.rects,
        },
        {
          annotation_id: temporaryId,
          locator: selection.locator,
          kind: kind === "note" ? "highlight" : kind,
          color,
          quote: selection.quote,
          note,
          rects: selection.rects,
          author: "user",
          created_at: now,
          updated_at: now,
        },
      );
      setSelection(null);
      window.getSelection()?.removeAllRanges();
    },
    [selection, material, saveMark],
  );

  const askAboutSelection = useCallback(() => {
    if (!selection || !material) return;
    window.dispatchEvent(
      new CustomEvent(READER_ASK_EVENT, {
        detail: {
          quote: selection.quote,
          locator: selection.locator,
          unit: material.unit,
        },
      }),
    );
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }, [selection, material]);

  // -- export --------------------------------------------------------------

  const runExport = useCallback(async () => {
    if (!material || exporting) return;
    setExporting(true);
    dismissError();
    try {
      const { blob, filename } = await fetchExport(material.material_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Revoke on the next frame: revoking synchronously can cancel the download
      // in some browsers before it has read the blob.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setError(error instanceof Error ? error.message : t("Export failed."));
    } finally {
      setExporting(false);
    }
  }, [material, exporting, t, dismissError, setError]);

  // -- render --------------------------------------------------------------

  const showAnnotations = annotationPanel ?? annotations.length > 0;
  const unitWord = material ? t(unitLabel(material.unit)) : "";
  const outlineRows = useMemo(
    () =>
      (material?.outline ?? []).filter((row) => row.title.trim().length > 0),
    [material],
  );

  return (
    <div className="relative flex h-full min-w-0 flex-col border-r border-[var(--border)] bg-[var(--background)]">
      <ReaderResizeHandle />
      <header className="flex h-11 shrink-0 items-center gap-1 border-b border-[var(--border)] px-2.5">
        <FileText
          size={14}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span
          className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]"
          title={material?.filename}
        >
          {material?.filename ?? t("Immersive reading")}
        </span>

        {material && (
          <>
            <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
              {unitWord} {currentLocator}/{material.unit_count}
            </span>
            {outlineRows.length > 0 && (
              <HeaderButton
                icon={List}
                label={t("Outline")}
                active={showOutline}
                onClick={() => setShowOutline((open) => !open)}
              />
            )}
            <HeaderButton
              icon={Crosshair}
              label={
                autoJump
                  ? t(
                      "Auto-jump on — the view follows what the assistant reads",
                    )
                  : t("Auto-jump off — the assistant will not move your view")
              }
              active={autoJump}
              onClick={toggleAutoJump}
            />
            <HeaderButton
              icon={exporting ? Loader2 : Download}
              label={t("Export annotated file")}
              spinning={exporting}
              onClick={() => void runExport()}
            />
            <HeaderButton
              icon={showAnnotations ? PanelRightClose : PanelRightOpen}
              label={t("Annotations")}
              active={showAnnotations}
              onClick={() => setAnnotationPanel(!showAnnotations)}
              // The panel itself only exists at `lg` and up — there is no room
              // for it beside the document on a narrow screen. Hiding the
              // trigger too keeps it from being a button that does nothing.
              className="hidden lg:inline-flex"
            />
            <HeaderButton
              icon={X}
              label={t("Close document")}
              onClick={closeMaterial}
            />
          </>
        )}
        {!material && (
          <HeaderButton icon={X} label={t("Close reader")} onClick={onClose} />
        )}
      </header>

      {notice && (
        <div
          role="alert"
          className="flex items-start gap-2 border-b border-[var(--destructive)]/25 bg-[var(--destructive)]/[0.06] px-3 py-2"
        >
          <p className="flex-1 text-[11.5px] leading-relaxed text-[var(--destructive)]">
            {notice}
          </p>
          <button
            type="button"
            onClick={dismissError}
            className="text-[var(--destructive)]/70 transition hover:text-[var(--destructive)]"
            aria-label={t("Dismiss")}
          >
            <X size={12} />
          </button>
        </div>
      )}

      {showOutline && material && outlineRows.length > 0 && (
        <nav className="dt-reader-scroll max-h-[34%] shrink-0 overflow-y-auto border-b border-[var(--border)] bg-[var(--muted)]/25 px-2 py-1.5">
          <ul>
            {outlineRows.map((row, index) => (
              <li key={`${row.locator}-${index}`}>
                <button
                  type="button"
                  onClick={() => {
                    requestJump(row.locator);
                    setShowOutline(false);
                  }}
                  style={{ paddingLeft: `${6 + (row.level - 1) * 12}px` }}
                  className="flex w-full items-baseline gap-2 rounded-md py-[3px] pr-2 text-left transition hover:bg-[var(--muted)]"
                >
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--foreground)]">
                    {row.title}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-[var(--muted-foreground)]">
                    {row.locator}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          {loadingMaterial ? (
            <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 size={14} className="animate-spin" />
              {t("Opening document…")}
            </div>
          ) : !material ? (
            <MaterialPicker
              onOpen={(candidate) => void openMaterial(candidate)}
            />
          ) : material.has_raw_view ? (
            <PdfDocumentView
              materialId={material.material_id}
              unitCount={material.unit_count}
              annotations={annotations}
              jump={jump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={setSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
            />
          ) : (
            <TextUnitView
              materialId={material.material_id}
              unit={material.unit}
              unitCount={material.unit_count}
              annotations={annotations}
              jump={jump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={setSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
            />
          )}
        </div>

        {material && showAnnotations && (
          <aside className="hidden w-[248px] shrink-0 border-l border-[var(--border)] bg-[var(--background)] lg:block">
            <AnnotationList
              annotations={annotations}
              unit={material.unit}
              activeId={activeAnnotationId}
              onSelect={(annotation) => {
                setActiveAnnotationId(annotation.annotation_id);
                requestJump(annotation.locator, annotation.quote || undefined);
              }}
              onDelete={(annotation) => void removeMark(annotation)}
            />
          </aside>
        )}
      </div>

      {selection && material && (
        <AnnotationPopover
          anchor={selection.anchor}
          quote={selection.quote}
          onHighlight={(color) => commitSelection("highlight", color)}
          onUnderline={(color) => commitSelection("underline", color)}
          onNote={(note, color) => commitSelection("note", color, note)}
          onAsk={askAboutSelection}
          onDismiss={() => setSelection(null)}
        />
      )}
    </div>
  );
}

function HeaderButton({
  icon: Icon,
  label,
  onClick,
  active,
  spinning,
  className = "",
}: {
  icon: typeof FileText;
  label: string;
  onClick: () => void;
  active?: boolean;
  spinning?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={spinning}
      onClick={onClick}
      className={`h-7 w-7 shrink-0 items-center justify-center rounded-lg transition disabled:cursor-default ${
        className || "inline-flex"
      } ${
        active
          ? "bg-[var(--primary)]/12 text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={14} className={spinning ? "animate-spin" : undefined} />
    </button>
  );
}
