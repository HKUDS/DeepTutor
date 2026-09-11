"use client";

import { browserStorage } from "@/shared/storage";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bookmark,
  BookmarkCheck,
  Crosshair,
  Download,
  FileText,
  Loader2,
  History,
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
import { citationTargetFromHref } from "@/lib/reading-citations";
import {
  fetchExport,
  getMaterial,
  getReadingPosition,
  saveReadingPosition,
  type AnnotationColor,
  type AnnotationItem,
  type MaterialDetail,
  type ReadingBookmark,
} from "@/lib/reading-api";
import { AnnotationList } from "./AnnotationList";
import { AnnotationPopover } from "./AnnotationPopover";
import { EpubDocumentView } from "./EpubDocumentView";
import {
  PdfDocumentView,
  type JumpRequest,
  type SelectionPayload,
} from "./PdfDocumentView";
import { ReadingExtensionBar } from "./ReadingExtensionBar";
import { TextUnitView, unitLabel } from "./TextUnitView";
import type { ReaderHeading } from "@/lib/reading-outline";
import {
  EMPTY_READING_HISTORY,
  loadReadingHistory,
  moveReadingHistory,
  pushReadingLocation,
  replaceCurrentReadingLocation,
  saveReadingHistory,
  selectReadingHistoryIndex,
  type ReadingLocationEntry,
  type ReadingLocationHistory,
} from "@/lib/reading-location-history";

/** Event the reader dispatches to prefill the composer from a selection. */
export const READER_ASK_EVENT = "dt:reader-ask";
const AUTO_JUMP_KEY = "dt.reader.autoJump";

function locationEntry(
  material: MaterialDetail,
  locator: number,
): ReadingLocationEntry {
  return {
    materialId: material.material_id,
    locator,
    title: material.title || material.filename,
    source: {
      filename: material.filename,
      unit: material.unit,
      mime: material.mime,
      renderMode: material.render_mode,
    },
  };
}

export interface ReaderPaneProps {
  onClose: () => void;
  sessionId?: string | null;
  /** User-owned navigation from the workspace's source outline. */
  externalJump?: JumpRequest | null;
  /**
   * Headings the text view discovers in the open unit. Only the rendered
   * document knows them, but the workspace navigator is where the reader
   * looks for structure — so they are reported up rather than shown here.
   */
  onHeadingsChange?: (headings: ReaderHeading[]) => void;
  onActiveHeadingChange?: (headingId: string | null) => void;
  /** Heading the navigator asked to scroll to. */
  headingJump?: {
    id: string;
    nonce: number;
    locator?: number;
    sourceHref?: string;
  } | null;
  /**
   * Kept places in this material. Owned by the workspace because the outline
   * panel lists them and this toolbar only needs to answer "is the page I am
   * on one of them?" — see `useReadingWorkspace`.
   */
  bookmarks?: ReadingBookmark[];
  onToggleBookmark?: (locator: number, label?: string) => void;
}

/**
 * The document surface of the Reading workspace, with its own annotations.
 * Source navigation, tabs and the outline are owned by the workspace shell —
 * this component renders one open document and everything anchored to it.
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
export function ReaderPane({
  onClose,
  sessionId,
  externalJump = null,
  onHeadingsChange,
  onActiveHeadingChange,
  headingJump = null,
  bookmarks = [],
  onToggleBookmark,
}: ReaderPaneProps) {
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
  // Whether the annotation popover is showing, kept apart from whether there
  // IS a selection. They used to be the same flag, and the popover dismisses
  // itself on a document-level, capture-phase `pointerdown` — so pressing a
  // toolbar button cleared `selection` before the click could land, React
  // re-rendered the button as `disabled` (all four selection-gated actions
  // declare `requires: ["selection"]`), and the browser then refused to
  // dispatch the rest of the activation sequence to a disabled control. No
  // fetch, no spinner, no error: 引导我 / 翻译成英文 / 翻译成中文 / 解释词汇
  // have been unreachable by pointer since the toolbar shipped.
  const [popoverOpen, setPopoverOpen] = useState(false);

  /** One place to open a selection, so the popover cannot drift out of step. */
  const openSelection = useCallback((payload: SelectionPayload | null) => {
    setSelection(payload);
    setPopoverOpen(payload !== null);
  }, []);

  /** Drop the selection entirely — it is stale, not merely unfocused. */
  const clearSelection = useCallback(() => {
    setSelection(null);
    setPopoverOpen(false);
  }, []);
  const [jump, setJump] = useState<JumpRequest | null>(null);
  // `null` = follow the document: show the panel once there is something in it.
  // An empty panel is a whole column of nothing next to the page, which reads as
  // a layout bug rather than an affordance. An explicit true/false means the
  // user decided, and that wins from then on.
  const [annotationPanel, setAnnotationPanel] = useState<boolean | null>(null);
  const [autoJump, setAutoJump] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [currentLocator, setCurrentLocator] = useState(1);
  const nonceRef = useRef(0);
  const headingLocatorRef = useRef(1);
  const jumpMaterialIdRef = useRef<string | null>(null);
  const [locationHistory, setLocationHistory] =
    useState<ReadingLocationHistory>(EMPTY_READING_HISTORY);
  const [historySessionId, setHistorySessionId] = useState<
    string | null | undefined
  >(undefined);
  const [showHistory, setShowHistory] = useState(false);
  const [unavailableMaterials, setUnavailableMaterials] = useState<Set<string>>(
    new Set(),
  );
  const navigationNonceRef = useRef(0);
  const pendingNavigationRef = useRef<{
    mode: "push" | "replay";
    materialId: string;
    locator: number;
  } | null>(null);
  const historyRestoreAttemptRef = useRef<{
    sessionId: string | null;
  } | null>(null);
  const externalJumpNonceRef = useRef(0);
  const positionSaveTimerRef = useRef<number | null>(null);
  /** Materials whose stored position has already been honoured. */
  const resumedMaterialRef = useRef("");
  const headingJumpNonceRef = useRef(0);
  const historyReady = historySessionId === (sessionId ?? null);

  // -- persisted auto-jump preference --------------------------------------

  useEffect(() => {
    try {
      const stored = browserStorage.readRaw("local", AUTO_JUMP_KEY);
      if (stored !== null) setAutoJump(stored === "1");
    } catch {
      // Private mode / storage disabled — keep the default.
    }
  }, []);

  const toggleAutoJump = useCallback(() => {
    setAutoJump((current) => {
      const next = !current;
      try {
        browserStorage.writeRaw("local", AUTO_JUMP_KEY, next ? "1" : "0");
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
      // Remember where the reader got to, so opening this material again
      // starts here instead of at page 1. EPUB writes its own position — a
      // CFI it needs to land inside a reflowed page — so leaving that alone
      // is the difference between resuming a paragraph and resuming a
      // chapter; the media stage does the same with a timestamp.
      if (material && material.render_mode !== "epub") {
        const materialId = material.material_id;
        const total = material.unit_count;
        if (positionSaveTimerRef.current) {
          clearTimeout(positionSaveTimerRef.current);
        }
        positionSaveTimerRef.current = window.setTimeout(() => {
          void saveReadingPosition(materialId, {
            locator,
            source_anchor: "",
            percentage: total > 0 ? locator / total : 0,
          }).catch(() => {
            // Reading continues when a background progress write fails.
          });
        }, 400);
      }
      if (material && historyReady) {
        const pending = pendingNavigationRef.current;
        if (
          pending?.materialId === material.material_id &&
          pending.locator !== locator
        ) {
          return;
        }
        setLocationHistory((current) => {
          const entry = locationEntry(material, locator);
          return current.entries[current.index]?.materialId ===
            material.material_id
            ? replaceCurrentReadingLocation(current, entry)
            : pushReadingLocation(current, entry);
        });
      }
    },
    [historyReady, material, reportViewport],
  );

  useEffect(() => {
    reportViewport({ selection: selection?.quote ?? "" });
  }, [selection, reportViewport]);

  // -- reader actions from the assistant -----------------------------------

  const requestJump = useCallback(
    (locator: number, quote?: string, targetMaterialId?: string) => {
      nonceRef.current += 1;
      setJump({ locator, quote, nonce: nonceRef.current });
      jumpMaterialIdRef.current =
        targetMaterialId ?? material?.material_id ?? null;
    },
    [material?.material_id],
  );

  const rememberExplicitLocation = useCallback(
    (locator: number) => {
      if (!material || !historyReady) return;
      setLocationHistory((current) =>
        pushReadingLocation(current, locationEntry(material, locator)),
      );
    },
    [historyReady, material],
  );

  const openHistoryEntry = useCallback(
    async (
      entry: ReadingLocationEntry,
      mode: "push" | "replay",
      forceOpen = false,
      candidate?: MaterialDetail,
    ) => {
      const navigationNonce = ++navigationNonceRef.current;
      if (forceOpen || entry.materialId !== material?.material_id) {
        setJump(null);
        pendingNavigationRef.current = {
          mode,
          materialId: entry.materialId,
          locator: entry.locator,
        };
        const opened = await openMaterial(candidate ?? entry.materialId);
        if (navigationNonce !== navigationNonceRef.current) return false;
        if (!opened) {
          setUnavailableMaterials((current) =>
            new Set(current).add(entry.materialId),
          );
          pendingNavigationRef.current = null;
          return false;
        }
      } else {
        pendingNavigationRef.current = null;
      }
      setUnavailableMaterials((current) => {
        if (!current.has(entry.materialId)) return current;
        const next = new Set(current);
        next.delete(entry.materialId);
        return next;
      });
      requestJump(entry.locator, undefined, entry.materialId);
      return true;
    },
    [material?.material_id, openMaterial, requestJump],
  );

  const selectHistoryEntry = useCallback(
    (index: number) => {
      const next = selectReadingHistoryIndex(locationHistory, index);
      const entry = next.entries[next.index];
      if (!entry) return;
      setLocationHistory(next);
      setShowHistory(false);
      void openHistoryEntry(entry, "replay");
    },
    [locationHistory, openHistoryEntry],
  );

  const stepHistory = useCallback(
    (delta: -1 | 1) => {
      const next = moveReadingHistory(locationHistory, delta);
      if (next.index === locationHistory.index) return;
      const entry = next.entries[next.index];
      if (!entry) return;
      setLocationHistory(next);
      void openHistoryEntry(entry, "replay");
    },
    [locationHistory, openHistoryEntry],
  );

  useEffect(() => {
    const scopedSessionId = sessionId ?? null;
    if (loadingMaterial) return;
    if (!material) return;
    if (historyRestoreAttemptRef.current?.sessionId === scopedSessionId) {
      return;
    }
    historyRestoreAttemptRef.current = { sessionId: scopedSessionId };
    const hadPendingNavigation = pendingNavigationRef.current !== null;
    navigationNonceRef.current += 1;
    pendingNavigationRef.current = null;
    const restored = scopedSessionId
      ? loadReadingHistory(scopedSessionId)
      : EMPTY_READING_HISTORY;
    setLocationHistory(restored);
    setUnavailableMaterials(new Set());
    setHistorySessionId(sessionId ?? null);
    const entry = restored.entries[restored.index];
    if (entry) void openHistoryEntry(entry, "replay", hadPendingNavigation);
    else if (hadPendingNavigation) closeMaterial();
    // Restore once per chat id. Material changes caused by the restore must not
    // restart it with a newly-created callback closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, loadingMaterial]);

  useEffect(() => {
    if (!historyReady || !sessionId || historySessionId !== sessionId) return;
    saveReadingHistory(sessionId, locationHistory);
  }, [historyReady, historySessionId, locationHistory, sessionId]);

  useEffect(() => {
    if (!historyReady || !material) return;
    const pending = pendingNavigationRef.current;
    if (pending?.materialId === material.material_id) {
      pendingNavigationRef.current = null;
      setCurrentLocator(pending.locator);
      if (pending.mode === "push") {
        setLocationHistory((current) =>
          pushReadingLocation(
            current,
            locationEntry(material, pending.locator),
          ),
        );
      }
      return;
    }
    if (pending) return;
    setJump(null);
    setCurrentLocator(1);
    setLocationHistory((current) =>
      pushReadingLocation(current, locationEntry(material, 1)),
    );
  }, [historyReady, material]);

  // -- resume where the reader left off ------------------------------------
  //
  // The effect above lands every newly-opened material on page 1. For a
  // 74-page document that a learner is halfway through, page 1 is the one
  // place they are certainly not trying to be — so the stored position, if
  // there is one, decides instead. Only once per material: after that the
  // reader is in charge, and re-running this would drag them back.
  //
  // EPUB and the media stage resume themselves (a CFI, a timestamp), and a
  // navigation already in flight — a citation, a history entry — is a
  // destination the learner asked for and outranks where they last stopped.
  useEffect(() => {
    const materialId = material?.material_id;
    if (!materialId || material?.render_mode === "epub") return;
    if (resumedMaterialRef.current === materialId) return;
    if (pendingNavigationRef.current) return;
    // Claimed before awaiting: this render is not the last one before the
    // request comes back.
    resumedMaterialRef.current = materialId;
    let cancelled = false;
    void getReadingPosition(materialId)
      .then((position) => {
        if (cancelled || position.locator <= 1) return;
        requestJump(position.locator);
      })
      .catch(() => {
        // Never opened before, or the read failed: page 1 is a fine start.
      });
    return () => {
      cancelled = true;
    };
  }, [material?.material_id, material?.render_mode, requestJump]);

  useEffect(
    () => () => {
      if (positionSaveTimerRef.current) {
        clearTimeout(positionSaveTimerRef.current);
      }
    },
    [],
  );

  const navigateCitation = useCallback(
    async (href: string | null | undefined) => {
      const target = citationTargetFromHref(href);
      if (!target) return false;
      if (target.materialId && target.materialId !== material?.material_id) {
        try {
          const candidate = await getMaterial(target.materialId);
          if (
            target.materialRevision &&
            candidate.revision !== target.materialRevision
          ) {
            setError(
              "This citation points to an older material revision that is not available in the reader.",
            );
            return true;
          }
          const entry = locationEntry(candidate, target.locator);
          await openHistoryEntry(entry, "push", false, candidate);
        } catch (caught) {
          setError(
            caught instanceof Error
              ? caught.message
              : "This citation's material could not be opened.",
          );
          return true;
        }
      } else if (
        target.materialRevision &&
        material?.revision !== target.materialRevision
      ) {
        setError(
          "This citation points to an older material revision that is not available in the reader.",
        );
        return true;
      }
      rememberExplicitLocation(target.locator);
      requestJump(target.locator);
      return true;
    },
    [
      material?.material_id,
      material?.revision,
      openHistoryEntry,
      rememberExplicitLocation,
      requestJump,
      setError,
    ],
  );

  useEffect(() => {
    if (!externalJump) return;
    if (externalJumpNonceRef.current === externalJump.nonce) return;
    externalJumpNonceRef.current = externalJump.nonce;
    rememberExplicitLocation(externalJump.locator);
    requestJump(externalJump.locator, externalJump.quote);
  }, [externalJump, rememberExplicitLocation, requestJump]);

  useEffect(() => {
    headingLocatorRef.current = currentLocator;
  }, [currentLocator]);

  useEffect(() => {
    if (!headingJump) return;
    if (headingJumpNonceRef.current === headingJump.nonce) return;
    headingJumpNonceRef.current = headingJump.nonce;
    rememberExplicitLocation(headingJump.locator ?? headingLocatorRef.current);
  }, [headingJump, rememberExplicitLocation]);

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
      if (locator >= 1) {
        rememberExplicitLocation(locator);
        requestJump(locator, detail.quote || undefined);
      }
    };
    window.addEventListener(READER_ACTION_EVENT, onReaderAction);
    return () =>
      window.removeEventListener(READER_ACTION_EVENT, onReaderAction);
  }, [material, autoJump, requestJump, mergeMark, rememberExplicitLocation]);

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
          'a[href^="#dt-locator-"], a[href^="#dt-material-"]',
        );
        void navigateCitation(anchor?.getAttribute("href"));
      }, 120);
      return () => window.clearTimeout(timer);
    };
    window.addEventListener(READER_TURN_END_EVENT, onTurnEnd);
    return () => window.removeEventListener(READER_TURN_END_EVENT, onTurnEnd);
  }, [autoJump, material, navigateCitation]);

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
      const element = event.target as HTMLElement | null;
      const anchor = element?.closest?.("a[href]") as HTMLAnchorElement | null;
      const citation = citationTargetFromHref(anchor?.getAttribute("href"));
      if (!citation) return;
      event.preventDefault();
      event.stopPropagation();
      void navigateCitation(anchor?.getAttribute("href"));
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [navigateCitation]);

  // -- annotations ---------------------------------------------------------

  const commitSelection = useCallback(
    (
      kind: "highlight" | "underline" | "note" | "citation",
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
          source_anchor: selection.sourceAnchor ?? "",
          selectors: selection.selectors ?? [],
        },
        {
          annotation_id: temporaryId,
          locator: selection.locator,
          material_revision: material.revision ?? 1,
          kind: kind === "note" ? "highlight" : kind,
          color,
          quote: selection.quote,
          note,
          rects: selection.rects,
          source_anchor: selection.sourceAnchor ?? "",
          selectors: selection.selectors ?? [],
          author: "user",
          created_at: now,
          updated_at: now,
        },
      );
      clearSelection();
      window.getSelection()?.removeAllRanges();
    },
    [selection, material, saveMark, clearSelection],
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
    clearSelection();
    window.getSelection()?.removeAllRanges();
  }, [selection, material, clearSelection]);

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
  const bookmarkedHere = bookmarks.some(
    (row) => row.locator === currentLocator,
  );
  const materialJump =
    material && jumpMaterialIdRef.current === material.material_id
      ? jump
      : null;

  return (
    <div className="relative flex h-full min-w-0 flex-col border-r border-[var(--border)] bg-[var(--background)]">
      <header className="flex h-11 shrink-0 items-center gap-1 border-b border-[var(--border)] px-2.5">
        <FileText
          size={14}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        {/* The title, not the filename. A material saved from the web is
            stored under its content hash, so this line read
            "65228f9f372d6e9b.md" for every page the learner opened — the one
            place in the reader that names what they are reading, spelling it
            as a checksum. The filename is worth keeping for uploads, where it
            is what the learner recognises, so it stays as the tooltip. */}
        <span
          className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]"
          title={material?.filename || material?.title}
        >
          {material?.title || material?.filename || t("Immersive reading")}
        </span>

        {locationHistory.entries.length > 0 && (
          <>
            <HeaderButton
              icon={ArrowLeft}
              label={t("Back")}
              disabled={locationHistory.index <= 0}
              onClick={() => stepHistory(-1)}
            />
            <HeaderButton
              icon={ArrowRight}
              label={t("Forward")}
              disabled={
                locationHistory.index < 0 ||
                locationHistory.index >= locationHistory.entries.length - 1
              }
              onClick={() => stepHistory(1)}
            />
            <HeaderButton
              icon={History}
              label={t("History")}
              active={showHistory}
              onClick={() => setShowHistory((current) => !current)}
            />
          </>
        )}

        {material && (
          <>
            {/* The one place the reader's position is stated. Monospace is for
                code, not for a line of UI copy; tabular figures alone stop the
                number from jittering as the learner scrolls. */}
            <span className="shrink-0 whitespace-nowrap text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
              {t("{{unit}} {{n}} / {{total}}", {
                unit: unitWord,
                n: currentLocator,
                total: material.unit_count,
              })}
            </span>
            {onToggleBookmark && (
              <HeaderButton
                icon={bookmarkedHere ? BookmarkCheck : Bookmark}
                label={
                  bookmarkedHere
                    ? t("Remove the bookmark on this {{unit}}", {
                        unit: unitWord.toLocaleLowerCase(),
                      })
                    : t("Bookmark this {{unit}}", {
                        unit: unitWord.toLocaleLowerCase(),
                      })
                }
                active={bookmarkedHere}
                onClick={() => onToggleBookmark(currentLocator)}
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
          </>
        )}
      </header>

      {showHistory && locationHistory.entries.length > 0 && (
        <div className="absolute top-11 right-2 z-30 max-h-72 w-72 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-1.5 shadow-xl">
          {[...locationHistory.entries]
            .map((entry, index) => ({ entry, index }))
            .reverse()
            .map(({ entry, index }) => {
              const unavailable = unavailableMaterials.has(entry.materialId);
              return (
                <button
                  key={`${entry.materialId}:${entry.locator}:${index}`}
                  type="button"
                  aria-current={
                    index === locationHistory.index ? "location" : undefined
                  }
                  onClick={() => selectHistoryEntry(index)}
                  className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-[var(--muted)] ${
                    index === locationHistory.index
                      ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]"
                      : "text-[var(--foreground)]"
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11.5px] font-medium">
                      {entry.title}
                    </span>
                    <span className="block truncate font-mono text-[10px] text-[var(--muted-foreground)]">
                      {t(unitLabel(entry.source?.unit || "section"))}{" "}
                      {entry.locator}
                      {unavailable ? ` · ${t("Unavailable")}` : ""}
                    </span>
                  </span>
                </button>
              );
            })}
        </div>
      )}

      {notice && (
        <div
          role="alert"
          className="flex items-start gap-2 border-b border-[color-mix(in_srgb,var(--destructive)_25%,transparent)] bg-[var(--destructive)]/[0.06] px-3 py-2"
        >
          <p className="flex-1 text-[11.5px] leading-relaxed text-[var(--destructive)]">
            {notice}
          </p>
          <button
            type="button"
            onClick={dismissError}
            className="text-[color-mix(in_srgb,var(--destructive)_70%,transparent)] transition hover:text-[var(--destructive)]"
            aria-label={t("Dismiss")}
          >
            <X size={12} />
          </button>
        </div>
      )}

      {material && (
        <ReadingExtensionBar
          materialId={material.material_id}
          locator={currentLocator}
          selectionLocator={selection?.locator}
          selection={selection?.quote}
          onError={setError}
        />
      )}

      <div className="relative flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          {loadingMaterial ? (
            <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 size={14} className="animate-spin" />
              {t("Opening document…")}
            </div>
          ) : !material ? (
            <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
              <p className="text-[12.5px] text-[var(--muted-foreground)]">
                {t("This document could not be opened.")}
              </p>
              <button
                type="button"
                onClick={onClose}
                className="text-[11.5px] font-medium text-[var(--primary)] underline-offset-2 hover:underline"
              >
                {t("Back to the library")}
              </button>
            </div>
          ) : material.render_mode === "epub" ? (
            <EpubDocumentView
              key={material.material_id}
              materialId={material.material_id}
              unitCount={material.unit_count}
              unitRefs={material.unit_refs}
              annotations={annotations}
              jump={materialJump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={openSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
              onHeadingsChange={onHeadingsChange}
              headingJump={headingJump}
              onError={setError}
            />
          ) : material.has_raw_view ? (
            <PdfDocumentView
              key={material.material_id}
              materialId={material.material_id}
              unitCount={material.unit_count}
              annotations={annotations}
              jump={materialJump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={openSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
            />
          ) : (
            <TextUnitView
              key={material.material_id}
              materialId={material.material_id}
              unit={material.unit}
              unitCount={material.unit_count}
              contentFormat={material.content_format}
              annotations={annotations}
              jump={materialJump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={openSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
              onHeadingsChange={onHeadingsChange}
              onActiveHeadingChange={onActiveHeadingChange}
              headingJump={headingJump}
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

      {/* `popoverOpen` and not just `selection`: dismissal now leaves the
          selection in place for the toolbar, so gating the mount on the
          selection alone would make Escape and outside-click stop working. */}
      {popoverOpen && selection && material && (
        <AnnotationPopover
          anchor={selection.anchor}
          quote={selection.quote}
          onHighlight={(color) => commitSelection("highlight", color)}
          onUnderline={(color) => commitSelection("underline", color)}
          onNote={(note, color) => commitSelection("note", color, note)}
          onCitation={(color) => commitSelection("citation", color)}
          onAsk={askAboutSelection}
          // Closes the popover WITHOUT dropping the selection, so the
          // toolbar's selection-gated actions stay reachable.
          onDismiss={() => setPopoverOpen(false)}
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
  disabled,
  className = "",
}: {
  icon: typeof FileText;
  label: string;
  onClick: () => void;
  active?: boolean;
  spinning?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={spinning || disabled}
      onClick={onClick}
      className={`h-7 w-7 shrink-0 items-center justify-center rounded-lg transition disabled:cursor-default ${
        className || "inline-flex"
      } ${
        active
          ? "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-35 disabled:hover:bg-transparent"
      }`}
    >
      <Icon size={14} className={spinning ? "animate-spin" : undefined} />
    </button>
  );
}
