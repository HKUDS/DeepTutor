"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookmarkPlus,
  BookOpenText,
  Crosshair,
  Download,
  ExternalLink,
  FileText,
  List,
  Loader2,
  Maximize2,
  MessageSquareText,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  goBackReadingHistory,
  goForwardReadingHistory,
  pushReadingHistory,
  type ReadingHistoryEntry,
  type ReadingHistoryState,
} from "@/lib/reading-history";
import { useReading } from "@/context/ReadingContext";
import {
  READER_ACTION_EVENT,
  READER_TURN_END_EVENT,
  type ReaderActionPayload,
} from "@/lib/reading-reader-action";
import { locatorFromHref } from "@/lib/reading-citations";
import {
  activateMaterialRevision,
  createMaterialFromUrl,
  fetchExport,
  getReadingPosition,
  listMaterialRevisions,
  saveMaterialToKb,
  saveReadingPosition,
  type AnnotationColor,
  type AnnotationItem,
  type MaterialInfo,
} from "@/lib/reading-api";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import { AnnotationList } from "./AnnotationList";
import { AnnotationPopover } from "./AnnotationPopover";
import { EpubDocumentView } from "./EpubDocumentView";
import { MaterialPicker } from "./MaterialPicker";
import {
  PdfDocumentView,
  type JumpRequest,
  type SelectionPayload,
} from "./PdfDocumentView";
import { ReaderResizeHandle } from "./ReaderResizeHandle";
import { ReadingExtensionBar } from "./ReadingExtensionBar";
import { ReaderOutline } from "./ReaderOutline";
import type { ReaderHeading } from "@/lib/reading-outline";
import { TextUnitView, unitLabel } from "./TextUnitView";

/** Event the reader dispatches to prefill the composer from a selection. */
export const READER_ASK_EVENT = "dt:reader-ask";
const AUTO_JUMP_KEY = "dt.reader.autoJump";

export interface ReaderPaneProps {
  onClose: () => void;
  learningActionsEnabled?: boolean;
  learningAgeBand?: string;
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
export function ReaderPane({
  onClose,
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
  const [jump, setJump] = useState<JumpRequest | null>(null);
  // `null` = follow the document: show the panel once there is something in it.
  // An empty panel is a whole column of nothing next to the page, which reads as
  // a layout bug rather than an affordance. An explicit true/false means the
  // user decided, and that wins from then on.
  const [annotationPanel, setAnnotationPanel] = useState<boolean | null>(null);
  const [showOutline, setShowOutline] = useState(false);
  const [outlineUserChoice, setOutlineUserChoice] = useState<boolean | null>(null);
  const [pageHeadings, setPageHeadings] = useState<ReaderHeading[]>([]);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const [headingJump, setHeadingJump] = useState<{ id: string; nonce: number } | null>(null);
  const [historyState, setHistoryState] = useState<ReadingHistoryState>({
    back: [],
    current: null,
    forward: [],
  });
  const [readingPercentage, setReadingPercentage] = useState(0);
  const [autoJump, setAutoJump] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [currentLocator, setCurrentLocator] = useState(1);
  const [focusMode, setFocusMode] = useState(false);
  const [assistantPanelOpen, setAssistantPanelOpen] = useState(false);
  const [revisions, setRevisions] = useState<MaterialInfo[]>([]);
  const [switchingRevision, setSwitchingRevision] = useState(false);
  const [kbChoices, setKbChoices] = useState<string[]>([]);
  const [savingToKb, setSavingToKb] = useState(false);
  const [openingTutorial, setOpeningTutorial] = useState(false);
  const readerRef = useRef<HTMLDivElement | null>(null);
  const nonceRef = useRef(0);
  const historyRef = useRef<ReadingHistoryState>({
    back: [],
    current: null,
    forward: [],
  });
  const lastJumpLocatorRef = useRef<number | null>(null);
  const restoringPositionRef = useRef("");
  const positionMaterialKeyRef = useRef("");
  const positionSaveTimerRef = useRef<number | null>(null);
  const positionMaterialKey = material
    ? `${material.material_id}:${material.revision_id ?? ""}`
    : "";
  if (positionMaterialKeyRef.current !== positionMaterialKey) {
    positionMaterialKeyRef.current = positionMaterialKey;
    restoringPositionRef.current = material?.material_id ?? "";
  }

  // -- persisted auto-jump preference --------------------------------------

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(AUTO_JUMP_KEY);
      if (stored !== null) setAutoJump(stored === "1");
    } catch {
      // Private mode / storage disabled — keep the default.
    }
  }, []);

  useEffect(() => {
    if (!focusMode) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setFocusMode(false);
        setAssistantPanelOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusMode]);

  useEffect(() => {
    const shell = readerRef.current?.closest<HTMLElement>(".dt-reader-shell");
    if (!shell) return;
    shell.dataset.readerFocus = focusMode ? "true" : "false";
    shell.dataset.readerAssistant =
      focusMode && assistantPanelOpen ? "true" : "false";
    return () => {
      delete shell.dataset.readerFocus;
      delete shell.dataset.readerAssistant;
    };
  }, [assistantPanelOpen, focusMode]);

  useEffect(() => {
    if (!material || material.source_type === "upload") {
      setRevisions([]);
      return;
    }
    let cancelled = false;
    void listMaterialRevisions(material.material_id)
      .then((rows) => {
        if (!cancelled) setRevisions(rows);
      })
      .catch(() => {
        if (!cancelled) setRevisions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [material]);

  useEffect(() => {
    if (material?.source_type !== "url_snapshot" || material.kb_name) return;
    void listKnowledgeBases()
      .then((rows) =>
        setKbChoices(
          rows.filter((row) => !row.read_only).map((row) => row.name),
        ),
      )
      .catch(() => setKbChoices([]));
  }, [material]);

  useEffect(() => {
    // Website tutorials are navigated by the source sidebar, so show that
    // structure automatically while preserving the user's ability to close it.
    if (material?.source_type === "kb_web_tutorial") {
      setShowOutline(true);
    }
  }, [material?.material_id, material?.source_type]);

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

  const requestJump = useCallback((locator: number, quote?: string) => {
    nonceRef.current += 1;
    lastJumpLocatorRef.current = locator;
    setJump({ locator, quote, nonce: nonceRef.current });
  }, []);

  const commitHistoryState = useCallback((next: ReadingHistoryState) => {
    historyRef.current = next;
    setHistoryState(next);
  }, []);

  const applyHistoryEntry = useCallback(
    (entry: ReadingHistoryEntry) => {
      requestJump(entry.locator, entry.quote);
      if (entry.headingId) {
        nonceRef.current += 1;
        setHeadingJump({ id: entry.headingId, nonce: nonceRef.current });
      }
    },
    [requestJump],
  );

  const navigateWithHistory = useCallback(
    (entry: ReadingHistoryEntry) => {
      const state = historyRef.current;
      const current =
        state.current ?? {
          locator: currentLocator,
          headingId: activeHeadingId ?? undefined,
        };
      commitHistoryState(pushReadingHistory({ ...state, current }, entry));
      applyHistoryEntry(entry);
    },
    [activeHeadingId, applyHistoryEntry, commitHistoryState, currentLocator],
  );

  const goReadingHistory = useCallback(
    (direction: "back" | "forward") => {
      const state = historyRef.current;
      const next =
        direction === "back"
          ? goBackReadingHistory(state)
          : goForwardReadingHistory(state);
      if (next === state || !next.current) return;
      commitHistoryState(next);
      applyHistoryEntry(next.current);
    },
    [applyHistoryEntry, commitHistoryState],
  );

  useEffect(() => {
    if (!material || material.render_mode === "epub") return;
    let cancelled = false;
    restoringPositionRef.current = material.material_id;
    void getReadingPosition(material.material_id)
      .then((position) => {
        if (cancelled) return;
        const locator = Math.min(
          material.unit_count,
          Math.max(1, position.locator || 1),
        );
        setCurrentLocator(locator);
        commitHistoryState({
          ...historyRef.current,
          current: { locator },
        });
        reportViewport({ locator });
        if (locator > 1 || position.source_anchor) {
          requestJump(locator, position.source_anchor || undefined);
        }
      })
      .catch(() => {
        // A missing position is equivalent to the first locator.
      })
      .finally(() => {
        if (!cancelled) restoringPositionRef.current = "";
      });
    return () => {
      cancelled = true;
    };
  }, [commitHistoryState, material, reportViewport, requestJump]);

  const handleVisibleLocator = useCallback(
    (locator: number) => {
      setCurrentLocator(locator);
      if (locator !== lastJumpLocatorRef.current) {
        commitHistoryState({
          ...historyRef.current,
          current: { locator },
        });
      }
      reportViewport({ locator });
      if (material) {
        setReadingPercentage(
          material.unit_count > 1
            ? (locator - 1) / (material.unit_count - 1)
            : 0,
        );
      }
      if (
        !material ||
        material.render_mode === "epub" ||
        restoringPositionRef.current === material.material_id
      ) {
        return;
      }
      if (positionSaveTimerRef.current) {
        window.clearTimeout(positionSaveTimerRef.current);
      }
      positionSaveTimerRef.current = window.setTimeout(() => {
        void saveReadingPosition(material.material_id, {
          locator,
          source_anchor: "",
          percentage:
            material.unit_count > 1
              ? (locator - 1) / (material.unit_count - 1)
              : 0,
        }).catch(() => {
          // Progress persistence must never interrupt reading.
        });
      }, 250);
    },
    [commitHistoryState, material, reportViewport],
  );

  useEffect(
    () => () => {
      if (positionSaveTimerRef.current) {
        window.clearTimeout(positionSaveTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    reportViewport({ selection: selection?.quote ?? "" });
  }, [selection, reportViewport]);

  // -- reader actions from the assistant -----------------------------------

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
      navigateWithHistory({ locator });
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [navigateWithHistory]);

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
          source_anchor: selection.sourceAnchor ?? "",
          selectors: selection.selectors ?? [],
        },
        {
          annotation_id: temporaryId,
          locator: selection.locator,
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

  const switchRevision = useCallback(
    async (revisionId: string) => {
      if (!material || !revisionId || switchingRevision) return;
      setSwitchingRevision(true);
      dismissError();
      try {
        const next = await activateMaterialRevision(
          material.material_id,
          revisionId,
        );
        await openMaterial(next);
      } catch (error) {
        setError(
          error instanceof Error ? error.message : t("Version could not be opened."),
        );
      } finally {
        setSwitchingRevision(false);
      }
    },
    [dismissError, material, openMaterial, setError, switchingRevision, t],
  );

  const saveToKb = useCallback(
    async (kbName: string) => {
      if (!material || !kbName || savingToKb) return;
      setSavingToKb(true);
      dismissError();
      try {
        const next = await saveMaterialToKb(material.material_id, kbName);
        await openMaterial(next);
      } catch (error) {
        setError(
          error instanceof Error ? error.message : t("This page could not be saved."),
        );
      } finally {
        setSavingToKb(false);
      }
    },
    [dismissError, material, openMaterial, savingToKb, setError, t],
  );

  const openWholeTutorial = useCallback(async () => {
    if (!material?.source_ref || openingTutorial) return;
    setOpeningTutorial(true);
    dismissError();
    try {
      const next = await createMaterialFromUrl(material.source_ref, {
        whole_tutorial: true,
      });
      await openMaterial(next);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : t("This tutorial could not be opened."),
      );
    } finally {
      setOpeningTutorial(false);
    }
  }, [dismissError, material, openMaterial, openingTutorial, setError, t]);

  useEffect(() => {
    if (!material) return;
    historyRef.current = { back: [], current: null, forward: [] };
    setHistoryState(historyRef.current);
    lastJumpLocatorRef.current = null;
    setPageHeadings([]);
    setActiveHeadingId(null);
    setHeadingJump(null);
    setReadingPercentage(material.reading_progress?.reading_percentage ?? 0);
    let stored: boolean | null = null;
    try {
      const raw = window.localStorage.getItem(`dt.reader.outline.${material.material_id}`);
      if (raw === "1" || raw === "0") stored = raw === "1";
    } catch {
      // Storage is optional; fall back to the material-type default.
    }
    setOutlineUserChoice(stored);
    const desktop = window.matchMedia("(min-width: 768px)").matches;
    setShowOutline(
      stored ??
        (desktop &&
          (material.source_type === "kb_web_tutorial" || material.render_mode === "epub")),
    );
  }, [material]);

  useEffect(() => {
    if (
      outlineUserChoice !== null ||
      !material ||
      !pageHeadings.length ||
      !window.matchMedia("(min-width: 768px)").matches
    ) {
      return;
    }
    if (pageHeadings.length >= 3) setShowOutline(true);
  }, [material, outlineUserChoice, pageHeadings.length]);

  const toggleOutline = useCallback(() => {
    setShowOutline((open) => {
      const next = !open;
      setOutlineUserChoice(next);
      if (material) {
        try {
          window.localStorage.setItem(
            `dt.reader.outline.${material.material_id}`,
            next ? "1" : "0",
          );
        } catch {
          // The current-session choice still works without persistence.
        }
      }
      return next;
    });
  }, [material]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "b") return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
      event.preventDefault();
      toggleOutline();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleOutline]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
      event.preventDefault();
      goReadingHistory(event.key === "ArrowLeft" ? "back" : "forward");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goReadingHistory]);

  // -- render --------------------------------------------------------------

  const showAnnotations = annotationPanel ?? annotations.length > 0;
  const unitWord = material ? t(unitLabel(material.unit)) : "";
  const outlineRows = useMemo(
    () =>
      (material?.outline ?? []).filter((row) => row.title.trim().length > 0),
    [material],
  );
  const outlinePaths = useMemo(
    () =>
      material?.kb_path
        ? material.kb_path
            .split("\n")
            .map((path) => path.trim())
            .filter(Boolean)
        : undefined,
    [material],
  );

  return (
    <div
      ref={readerRef}
      data-focus-mode={focusMode ? "true" : "false"}
      className={
        focusMode
          ? "fixed inset-0 z-50 flex min-w-0 flex-col bg-[var(--background)]"
          : "relative flex h-full min-w-0 flex-col border-r border-[var(--border)] bg-[var(--background)]"
      }
    >
      {!focusMode && <ReaderResizeHandle />}
      <header
        className={`flex h-11 shrink-0 items-center gap-1 border-b border-[var(--border)] ${
          focusMode ? "overflow-visible px-2" : "overflow-x-auto px-2.5"
        }`}
      >
        {material && (outlineRows.length > 0 || pageHeadings.length > 0) && (
          <button
            type="button"
            onClick={toggleOutline}
            title={t("Contents")}
            aria-label={t("Contents")}
            aria-pressed={showOutline}
            className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2 text-[12px] font-medium transition ${
              showOutline
                ? "border-[var(--primary)]/30 bg-[var(--primary)]/12 text-[var(--primary)]"
                : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <List size={15} />
            <span className="hidden sm:inline">{t("Contents")}</span>
          </button>
        )}
        {material && (
          <>
            <HeaderButton
              icon={ArrowLeft}
              label={t("Go back")}
              disabled={!historyState.back.length}
              onClick={() => goReadingHistory("back")}
            />
            <HeaderButton
              icon={ArrowRight}
              label={t("Go forward")}
              disabled={!historyState.forward.length}
              onClick={() => goReadingHistory("forward")}
            />
          </>
        )}
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
              icon={focusMode ? Minimize2 : Maximize2}
              label={focusMode ? t("Exit focus mode") : t("Focus mode")}
              active={focusMode}
              onClick={() => {
                setFocusMode((value) => !value);
                if (focusMode) setAssistantPanelOpen(false);
              }}
            />
            {focusMode && (
              <HeaderButton
                icon={MessageSquareText}
                label={
                  assistantPanelOpen
                    ? t("Hide assistant")
                    : t("Show assistant")
                }
                active={assistantPanelOpen}
                onClick={() => setAssistantPanelOpen((value) => !value)}
              />
            )}
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
              className={focusMode ? "inline-flex" : "hidden lg:inline-flex"}
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
      {material && (
        <div className="h-0.5 shrink-0 bg-[var(--muted)]">
          <div
            className="h-full bg-[var(--primary)] transition-[width]"
            style={{ width: `${Math.round(Math.min(1, Math.max(0, readingPercentage)) * 100)}%` }}
          />
        </div>
      )}

      {material && material.source_type !== "upload" && (
        <div className="flex min-h-9 shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-[var(--border)] bg-[var(--card)]/45 px-3 py-1.5 text-[10.5px] text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">
            {material.source_type === "url_snapshot"
              ? t("Web snapshot")
              : material.source_type === "kb_web_tutorial"
                ? t("Website tutorial")
                : material.source_type === "derived_epub"
                  ? t("Bilingual EPUB")
                  : t("Knowledge base file")}
          </span>
          {material.captured_at ? (
            <span>
              {t("Captured")} {new Date(material.captured_at * 1000).toLocaleString()}
            </span>
          ) : null}
          {material.source_url && (
            <a
              href={material.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
            >
              <ExternalLink size={10} />
              {t("View original")}
            </a>
          )}
          {material.source_type === "url_snapshot" &&
            material.tutorial_available && (
              <button
                type="button"
                onClick={() => void openWholeTutorial()}
                disabled={openingTutorial}
                className="inline-flex h-6 items-center gap-1 rounded border border-[var(--border)] px-1.5 font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
              >
                {openingTutorial ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : (
                  <BookOpenText size={10} />
                )}
                {t("Read whole tutorial")}
              </button>
            )}
          {material.navigation_kind === "inferred" && (
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {t("Auto-generated structure")}
            </span>
          )}
          {revisions.length > 1 && (
            <label className="ml-auto inline-flex items-center gap-1">
              <span>{t("Version")}</span>
              <select
                value={material.revision_id ?? ""}
                disabled={switchingRevision}
                onChange={(event) => void switchRevision(event.target.value)}
                className="h-6 max-w-[180px] rounded border border-[var(--border)] bg-[var(--background)] px-1.5 text-[10.5px]"
              >
                {revisions.map((revision) => (
                  <option key={revision.revision_id} value={revision.revision_id}>
                    {revision.captured_at
                      ? new Date(revision.captured_at * 1000).toLocaleString()
                      : revision.revision_id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {material.source_type === "url_snapshot" && !material.kb_name &&
            kbChoices.length > 0 && (
              <label className={revisions.length > 1 ? "" : "ml-auto"}>
                <span className="sr-only">{t("Save to knowledge base")}</span>
                <select
                  value=""
                  disabled={savingToKb}
                  onChange={(event) => void saveToKb(event.target.value)}
                  className="h-6 max-w-[190px] rounded border border-[var(--border)] bg-[var(--background)] px-1.5 text-[10.5px] text-[var(--foreground)]"
                >
                  <option value="">
                    {savingToKb ? t("Saving…") : t("Save to knowledge base…")}
                  </option>
                  {kbChoices.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          {material.kb_name && (
            <span className="inline-flex items-center gap-1">
              <BookmarkPlus size={10} /> {t("Saved to KB")}
            </span>
          )}
        </div>
      )}

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

      {material ? (
        <ReadingExtensionBar
          materialId={material.material_id}
          locator={currentLocator}
          selection={selection ? {
            quote: selection.quote,
            sourceAnchor: selection.sourceAnchor,
          } : null}
          onError={setError}
        />
      ) : null}

      <div className="relative flex min-h-0 flex-1">
        {showOutline && material && (outlineRows.length > 0 || pageHeadings.length > 0) && (
          <ReaderOutline
            rows={outlineRows}
            sourcePaths={outlinePaths}
            pageHeadings={pageHeadings}
            activeHeadingId={activeHeadingId}
            currentLocator={currentLocator}
            onNavigate={(locator) => {
              navigateWithHistory({ locator });
              if (!window.matchMedia("(min-width: 768px)").matches) {
                setShowOutline(false);
              }
            }}
            onNavigateHeading={(heading) => {
              navigateWithHistory({
                locator: currentLocator,
                headingId: heading.id,
              });
            }}
            onClose={() => setShowOutline(false)}
            sourceType={material.source_type}
          />
        )}
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
          ) : material.render_mode === "epub" ? (
            <EpubDocumentView
              materialId={material.material_id}
              unitCount={material.unit_count}
              unitRefs={material.unit_refs}
              annotations={annotations}
              jump={jump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={setSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
              onHeadingsChange={setPageHeadings}
              headingJump={headingJump}
              onReadingProgressChange={setReadingPercentage}
              onError={setError}
              bilingualAvailable={material.bilingual_available}
              onOpenMaterial={(candidate) => void openMaterial(candidate)}
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
              contentFormat={material.content_format}
              bilingualAvailable={material.bilingual_available}
              annotations={annotations}
              jump={jump}
              highlightedAnnotationId={activeAnnotationId}
              onSelection={setSelection}
              onAnnotationClick={(annotation) =>
                setActiveAnnotationId(annotation.annotation_id)
              }
              onVisibleLocatorChange={handleVisibleLocator}
              onHeadingsChange={setPageHeadings}
              onActiveHeadingChange={setActiveHeadingId}
              headingJump={headingJump}
            />
          )}
        </div>

        {material && showAnnotations && (
          <aside
            className={
              focusMode
                ? "absolute inset-y-0 right-0 z-30 w-[min(320px,86vw)] border-l border-[var(--border)] bg-[var(--background)] shadow-xl lg:static lg:w-[280px] lg:shrink-0 lg:shadow-none"
                : "hidden w-[248px] shrink-0 border-l border-[var(--border)] bg-[var(--background)] lg:block"
            }
          >
            <AnnotationList
              annotations={annotations}
              unit={material.unit}
              activeId={activeAnnotationId}
              onSelect={(annotation) => {
                setActiveAnnotationId(annotation.annotation_id);
                navigateWithHistory({
                  locator: annotation.locator,
                  quote: annotation.quote || undefined,
                });
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
      {focusMode && assistantPanelOpen && (
        <button
          type="button"
          onClick={() => setAssistantPanelOpen(false)}
          aria-label={t("Hide assistant")}
          title={t("Hide assistant")}
          className="fixed left-1 top-1 z-[102] inline-flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--card)] text-[var(--foreground)] shadow md:hidden"
        >
          <PanelRightClose size={15} />
        </button>
      )}
      {focusMode && material && (
        <button
          type="button"
          onClick={() => {
            setFocusMode(false);
            setAssistantPanelOpen(false);
          }}
          aria-label={t("Exit focus mode")}
          title={t("Exit focus mode")}
          className="fixed right-2 top-2 z-[110] inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] shadow-lg"
          style={
            assistantPanelOpen
              ? { right: "calc(var(--reader-assistant-width, 380px) + 8px)" }
              : undefined
          }
        >
          <Minimize2 size={16} />
        </button>
      )}
      {focusMode && material && assistantPanelOpen && (
        <button
          type="button"
          onClick={() => setAssistantPanelOpen(false)}
          aria-label={t("Hide assistant")}
          title={t("Hide assistant")}
          className="fixed bottom-5 z-[110] inline-flex h-10 w-8 items-center justify-center rounded-l-xl border border-r-0 border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] shadow-lg"
          style={{ right: "var(--reader-assistant-width, 380px)" }}
        >
          <PanelRightClose size={16} />
        </button>
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
  disabled = false,
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
      disabled={disabled || spinning}
      onClick={onClick}
      className={`h-7 w-7 shrink-0 items-center justify-center rounded-lg transition disabled:cursor-default disabled:opacity-35 disabled:hover:bg-transparent ${
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
