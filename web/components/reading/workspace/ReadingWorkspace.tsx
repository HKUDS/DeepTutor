"use client";

import { browserStorage } from "@/shared/storage";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  ChevronDown,
  CircleAlert,
  GraduationCap,
  Highlighter,
  History,
  Link2,
  Loader2,
  MoreHorizontal,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  StickyNote,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { JumpRequest } from "@/components/reading/PdfDocumentView";
import { READER_ASK_EVENT, ReaderPane } from "@/components/reading/ReaderPane";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import type { ReaderHeading } from "@/lib/reading-outline";
import { setReadingViewport } from "@/lib/reading-turn-state";
import { listNotebooks, type NotebookSummary } from "@/lib/notebook-api";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import {
  getReadingPosition,
  getMaterial,
  getUnitText,
  rawMaterialUrl,
  saveReadingPosition,
  uploadMaterial,
  type OutlineRow,
  type UnitReference,
} from "@/lib/reading-api";
import {
  READER_ACTION_EVENT,
  READER_TURN_END_EVENT,
  type ReaderActionPayload,
} from "@/lib/reading-reader-action";
import { mediaTimeFromHref } from "@/lib/reading-media-citations";
import {
  linkReadingConversation,
  listReadingConversations,
  retryReadingMaterial,
  unlinkReadingConversation,
  type ReadingConversation,
  type ReadingLibraryMaterial,
} from "@/lib/reading-workspace-api";
import { MediaReadingStage } from "./MediaReadingStage";
import { SourceNavigator } from "./SourceNavigator";
import {
  CompanionWelcome,
  EmptyWorkspace,
  MaterialFailure,
  MaterialProcessing,
  MenuItem,
  iconForMaterial,
} from "./WorkspaceChrome";
import {
  ConversationLinkDialog,
  ConversationMenu,
  NotebookCaptureDialog,
  OrganizedNotesDialog,
  WorkspaceConfirmDialog,
  WorkspaceValueDialog,
} from "./dialogs";
import { AddMaterialsDialog } from "@/components/reading/library/AddMaterialsDialog";
import { ReadingCompanion } from "./ReadingCompanion";
import { useReadingWorkspace } from "./useReadingWorkspace";

interface ReaderAskDetail {
  quote?: string;
  locator?: number;
  unit?: string;
}

export function ReadingWorkspacePage() {
  const params = useParams<{ workspaceId: string; sessionId?: string }>();
  const workspaceId = params.workspaceId;
  const sessionIdParam = params.sessionId?.trim() || null;
  const courseId = useSearchParams().get("course")?.trim() ?? "";
  const router = useRouter();
  const { t } = useTranslation();
  // The shell only needs to *send* (guided one-click prompts). Rendering the
  // transcript, editing, branching and cancelling all belong to the companion,
  // which reads them off the same context.
  const { state, sendMessage } = useChatStateAdapter();

  const {
    workspace,
    setWorkspace,
    conversations,
    setConversations,
    loading,
    error,
    notice,
    setNotice,
    material,
    annotations,
    activeTab,
    activeConversation,
    linkedSessionIds,
    activeLocator,
    setActiveLocator,
    transcript,
    organizedNotes,
    setOrganizedNotes,
    refresh,
    switchMaterial,
    removeMaterial,
    newConversation,
    openConversation,
    renameConversation,
    deleteConversation,
    organizeNotes,
    buildMasteryPath,
    renameWorkspace,
    reportViewport,
  } = useReadingWorkspace(workspaceId, sessionIdParam, courseId);

  // View-only state: what the reader is pointing at and which panels are open.
  const [transcriptSearch, setTranscriptSearch] = useState("");
  const [selection, setSelection] = useState<{
    quote: string;
    locator: number;
  } | null>(null);
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
  // Persisted so a reader who likes a wider (or narrower) companion does not
  // have to redo it every session; the default mirrors the fixed width the
  // panel used before it became resizable. Lazy-initialized (not an effect)
  // because it never reaches server-rendered markup — `gridStyle` below stays
  // `undefined` until `isDesktopWide` flips true on the client — so there is
  // no hydration mismatch to guard against.
  const [companionWidth, setCompanionWidth] = useState(() => {
    if (typeof window === "undefined") return 380;
    try {
      const stored = Number(
        browserStorage.readRaw("local", "dt.reader.companionWidth"),
      );
      return Number.isFinite(stored) && stored >= 300 && stored <= 640
        ? stored
        : 380;
    } catch {
      return 380;
    }
  });
  const [isDesktopWide, setIsDesktopWide] = useState(false);

  // A Course Study hand-off may have written the opening line before sending
  // the learner here. Consumed once, so a refresh does not retype it.
  useEffect(() => {
    const pending = consumePendingPrompt("immersive_reading");
    if (pending) prefillInputRef.current?.(pending);
  }, []);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1280px)");
    const update = () => setIsDesktopWide(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  const [showSessions, setShowSessions] = useState(false);
  const [showLinker, setShowLinker] = useState(false);
  const [showNotebook, setShowNotebook] = useState(false);
  const [showAddSource, setShowAddSource] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [showMastery, setShowMastery] = useState(false);
  const [removeTarget, setRemoveTarget] =
    useState<ReadingLibraryMaterial | null>(null);
  const [renameConversationTarget, setRenameConversationTarget] =
    useState<ReadingConversation | null>(null);
  const [deleteConversationTarget, setDeleteConversationTarget] =
    useState<ReadingConversation | null>(null);
  const [companionOpen, setCompanionOpen] = useState(true);
  const [navigatorOpen, setNavigatorOpen] = useState(false);
  const [navigatorCollapsed, setNavigatorCollapsed] = useState(false);
  const [documentJump, setDocumentJump] = useState<JumpRequest | null>(null);
  const [pageHeadings, setPageHeadings] = useState<ReaderHeading[]>([]);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const [headingJump, setHeadingJump] = useState<{
    id: string;
    nonce: number;
    locator?: number;
    sourceHref?: string;
  } | null>(null);

  useEffect(() => {
    // On narrower screens the source remains the base layer. The outline and
    // companion open as intentional sheets instead of squeezing the reader
    // into an unusable three-column layout.
    const frame = window.requestAnimationFrame(() => {
      if (!window.matchMedia("(min-width: 1280px)").matches) {
        setCompanionOpen(false);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const onAsk = (event: Event) => {
      const detail = (event as CustomEvent<ReaderAskDetail>).detail;
      const quote = String(detail?.quote ?? "").trim();
      if (!quote) return;
      setSelection({ quote, locator: Number(detail.locator || activeLocator) });
      setReadingViewport({
        locator: Number(detail.locator || activeLocator),
        selection: quote,
      });
      setCompanionOpen(true);
      prefillInputRef.current?.("");
    };
    window.addEventListener(READER_ASK_EVENT, onAsk);
    return () => window.removeEventListener(READER_ASK_EVENT, onAsk);
  }, [activeLocator]);

  // Guided one-click actions (quick-action row, empty-state suggestions,
  // "organize notes") send immediately without ever touching the composer's
  // own text — that box is reserved for what the learner types themselves.
  const sendQuickPrompt = useCallback(
    (prompt: string) => {
      const content = prompt.trim();
      if (!content || state.isStreaming) return;
      if (selection) {
        setReadingViewport({
          locator: selection.locator,
          selection: selection.quote,
        });
      }
      sendMessage(content, undefined, undefined, undefined, linkedSessionIds);
      setSelection(null);
      window.setTimeout(() => setReadingViewport({ selection: "" }), 0);
    },
    [linkedSessionIds, selection, sendMessage, state.isStreaming],
  );

  const startCompanionResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = companionWidth;
      const reserved = navigatorCollapsed ? 420 : 650;
      const max = Math.max(300, Math.min(640, window.innerWidth - reserved));
      const onMove = (moveEvent: PointerEvent) => {
        const next = startWidth + (startX - moveEvent.clientX);
        setCompanionWidth(Math.min(max, Math.max(300, Math.round(next))));
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        setCompanionWidth((current) => {
          try {
            browserStorage.writeRaw(
              "local",
              "dt.reader.companionWidth",
              String(current),
            );
          } catch {
            // A blocked or private store just resets to default next time.
          }
          return current;
        });
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [companionWidth, navigatorCollapsed],
  );

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 bg-[var(--background)] text-[12px] text-[var(--muted-foreground)] dark:bg-[var(--background)]">
        <Loader2 size={16} className="animate-spin" />
        {t("Opening collection…")}
      </div>
    );
  }

  if (error && !workspace) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-[var(--background)] px-6 text-center dark:bg-[var(--background)]">
        <CircleAlert size={25} className="text-[var(--primary)]" />
        <p className="mt-3 text-[13px] font-medium">{error}</p>
        <Link
          href="/reading"
          className="mt-5 rounded-xl bg-[var(--primary)] px-4 py-2 text-[11px] font-semibold text-[var(--primary-foreground)]"
        >
          {t("Back to library")}
        </Link>
      </div>
    );
  }

  if (!workspace) return null;

  const activeExtractor = material?.extractor || "";
  const transcriptUnavailable = [
    "youtube-no-captions",
    "bilibili-no-subtitles",
    "bilibili-chapters-only",
  ].includes(activeExtractor);
  const chaptersOnly = activeExtractor === "bilibili-chapters-only";

  const isMedia =
    activeTab?.material.source_kind === "youtube" ||
    activeTab?.material.render_mode === "video" ||
    activeTab?.material.render_mode === "audio";

  // At desktop width the companion column is drag-resizable, so its track is
  // driven by JS state rather than the Tailwind classes below — a narrow
  // hairline "handle" track sits between the reader and the companion only
  // in this case. Every other combination (companion closed, or too narrow
  // for a three-column layout) is exactly what the className already says.
  const showResizeHandle = isDesktopWide && companionOpen;
  const gridStyle: React.CSSProperties | undefined = showResizeHandle
    ? {
        gridTemplateColumns: navigatorCollapsed
          ? `minmax(360px,1fr) 5px ${companionWidth}px`
          : `minmax(184px,230px) minmax(360px,1fr) 5px ${companionWidth}px`,
      }
    : undefined;

  return (
    <main className="reading-v2 flex h-full min-h-0 flex-col overflow-hidden bg-[var(--background)] text-[var(--foreground)] dark:bg-[var(--background)] dark:text-[var(--foreground)]">
      <header className="flex h-11 shrink-0 items-center gap-1.5 border-b border-[var(--border)] bg-[var(--card)] px-2.5">
        <Link
          href="/reading"
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
          aria-label={t("Back to collections")}
        >
          <ArrowLeft size={14} />
        </Link>
        <button
          type="button"
          onClick={() => setShowRename(true)}
          className="max-w-[240px] shrink-0 truncate font-serif text-[13.5px] font-semibold tracking-[-0.01em] transition hover:text-[var(--primary)]"
          title={t("Rename collection")}
        >
          {workspace.title}
        </button>
        <span className="mx-1 h-4 w-px shrink-0 bg-[var(--border)]" />

        {/* The collection's materials. They are members of the collection, not
            browser tabs: closing one removes it, so the control says so and
            only the open material offers it. */}
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {workspace.tabs.map((tab) => {
            const active =
              tab.material.material_id === workspace.active_material_id;
            const TabIcon = iconForMaterial(tab.material);
            const busy =
              tab.material.status === "processing" ||
              tab.material.status === "queued";
            return (
              <span
                key={tab.material.material_id}
                className={`flex h-7 shrink-0 items-center gap-1.5 rounded-md pl-2 pr-1.5 text-[11px] transition ${
                  active
                    ? "bg-[var(--background)] font-semibold text-[var(--foreground)] shadow-[inset_0_0_0_1px_var(--border)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => void switchMaterial(tab.material)}
                  className="flex min-w-0 items-center gap-1.5"
                >
                  {busy ? (
                    <Loader2 size={11} className="shrink-0 animate-spin" />
                  ) : (
                    <TabIcon size={11} className="shrink-0" />
                  )}
                  <span className="max-w-[168px] truncate">
                    {tab.material.title}
                  </span>
                </button>
                {active && workspace.tabs.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setRemoveTarget(tab.material)}
                    className="shrink-0 text-[var(--muted-foreground)] transition hover:text-[var(--destructive)]"
                    aria-label={t("Remove from collection")}
                    title={t("Remove from collection")}
                  >
                    <X size={11} />
                  </button>
                )}
              </span>
            );
          })}
          <button
            type="button"
            onClick={() => setShowAddSource(true)}
            className="flex size-6 shrink-0 items-center justify-center rounded-md border border-dashed border-[var(--border)] text-[var(--muted-foreground)] transition hover:border-[var(--primary)] hover:text-[var(--primary)]"
            aria-label={t("Add material")}
            title={t("Add material")}
          >
            <Plus size={11} />
          </button>
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {notice && (
            <span className="hidden max-w-[220px] truncate px-2 text-[10px] text-[var(--muted-foreground)] 2xl:inline">
              {notice}
            </span>
          )}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowActions((current) => !current)}
              className="flex size-7 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
              aria-label={t("Collection actions")}
              aria-expanded={showActions}
            >
              <MoreHorizontal size={14} />
            </button>
            {showActions && (
              <div className="absolute right-0 top-8 z-40 w-48 rounded-lg border border-[var(--border)] bg-[var(--card)] p-1 text-[11.5px] shadow-md dark:bg-[var(--popover)]">
                <MenuItem
                  icon={StickyNote}
                  label={t("Organize notes")}
                  onClick={() => {
                    setShowActions(false);
                    void organizeNotes();
                  }}
                />
                <MenuItem
                  icon={NotebookPen}
                  label={t("Send to Notebook")}
                  onClick={() => {
                    setShowActions(false);
                    setShowNotebook(true);
                  }}
                />
                <MenuItem
                  icon={GraduationCap}
                  label={t("Build Mastery Path")}
                  onClick={() => {
                    setShowActions(false);
                    setShowMastery(true);
                  }}
                />
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              if (window.matchMedia("(min-width: 1024px)").matches) {
                setNavigatorCollapsed((current) => !current);
              } else {
                setCompanionOpen(false);
                setNavigatorOpen((current) => !current);
              }
            }}
            className="flex size-7 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--primary)]"
            aria-label={
              navigatorCollapsed ? t("Expand contents") : t("Collapse contents")
            }
            aria-expanded={navigatorOpen || !navigatorCollapsed}
          >
            {navigatorCollapsed ? (
              <PanelLeftOpen size={14} />
            ) : (
              <PanelLeftClose size={14} />
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              setNavigatorOpen(false);
              setCompanionOpen((current) => !current);
            }}
            className={`flex size-7 items-center justify-center rounded-md transition hover:bg-[var(--muted)] ${
              companionOpen
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)]"
            }`}
            aria-label={t("Reading companion")}
            aria-expanded={companionOpen}
          >
            {companionOpen ? (
              <PanelRightClose size={14} />
            ) : (
              <PanelRightOpen size={14} />
            )}
          </button>
        </div>
      </header>

      <div
        className={`relative grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] overflow-hidden ${
          companionOpen
            ? navigatorCollapsed
              ? "grid-cols-[minmax(0,1fr)] xl:grid-cols-[minmax(360px,1fr)_minmax(330px,420px)]"
              : "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)] xl:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)_minmax(330px,420px)]"
            : navigatorCollapsed
              ? "grid-cols-[minmax(0,1fr)]"
              : "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(0,1fr)]"
        }`}
        style={gridStyle}
      >
        {(navigatorOpen || companionOpen) && (
          <button
            type="button"
            className="absolute inset-0 z-20 bg-[var(--overlay)] xl:hidden"
            onClick={() => {
              setNavigatorOpen(false);
              setCompanionOpen(false);
            }}
            aria-label={t("Close panels")}
          />
        )}
        <SourceNavigator
          material={activeTab?.material ?? null}
          outline={material?.outline ?? []}
          pageHeadings={pageHeadings}
          activeHeadingId={activeHeadingId}
          onNavigateHeading={(heading) =>
            setHeadingJump((current) => ({
              id: heading.id,
              nonce: (current?.nonce ?? 0) + 1,
              locator: heading.locator,
              sourceHref: heading.sourceHref,
            }))
          }
          refs={material?.unit_refs ?? []}
          transcript={material?.unit === "segment" ? transcript : []}
          transcriptUnavailable={transcriptUnavailable}
          chaptersOnly={chaptersOnly}
          search={transcriptSearch}
          onSearch={setTranscriptSearch}
          activeLocator={activeLocator}
          annotationCount={annotations.length}
          unitCount={material?.unit_count ?? 0}
          mobileOpen={navigatorOpen}
          desktopOpen={!navigatorCollapsed}
          onMobileClose={() => setNavigatorOpen(false)}
          onCollapse={() => setNavigatorCollapsed(true)}
          onNavigate={(locator, quote) => {
            setActiveLocator(locator);
            reportViewport({ locator });
            setDocumentJump((current) => ({
              locator,
              quote,
              nonce: (current?.nonce ?? 0) + 1,
            }));
            if (quote) {
              setSelection({ quote, locator });
              setReadingViewport({ locator, selection: quote });
            }
          }}
        />

        <section className="relative min-h-0 min-w-0 overflow-hidden border-r border-[var(--border)] bg-[var(--secondary)] dark:border-[var(--border)] dark:bg-[var(--secondary)]">
          {!activeTab ? (
            <EmptyWorkspace onAdd={() => setShowAddSource(true)} />
          ) : activeTab.material.status === "failed" ? (
            <MaterialFailure
              material={activeTab.material}
              onRetry={async () => {
                await retryReadingMaterial(activeTab.material.material_id);
                await refresh();
              }}
            />
          ) : activeTab.material.status !== "ready" ? (
            <MaterialProcessing material={activeTab.material} />
          ) : isMedia ? (
            <MediaReadingStage
              key={activeTab.material.material_id}
              material={activeTab.material}
              title={activeTab.material.title}
              refs={material?.unit_refs ?? []}
              transcriptUnavailable={transcriptUnavailable}
              chaptersOnly={chaptersOnly}
              activeLocator={activeLocator}
              onLocatorChange={(locator) => {
                setActiveLocator(locator);
                reportViewport({ locator });
              }}
            />
          ) : (
            <div className="h-full [&>div]:border-r-0">
              <ReaderPane
                sessionId={state.sessionId ?? sessionIdParam}
                externalJump={documentJump}
                onHeadingsChange={setPageHeadings}
                onActiveHeadingChange={setActiveHeadingId}
                headingJump={headingJump}
                onClose={() => router.push("/reading")}
              />
            </div>
          )}

          {selection && (
            <div className="absolute bottom-4 left-1/2 z-30 flex max-w-[82%] -translate-x-1/2 items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 shadow-[0_12px_36px_rgba(0,0,0,.16)] dark:border-[var(--border)] dark:bg-[var(--popover)]">
              <Highlighter
                size={13}
                className="shrink-0 text-[var(--primary)]"
              />
              <p className="min-w-0 flex-1 truncate text-[10.5px] text-[var(--muted-foreground)] dark:text-[var(--foreground)]">
                “{selection.quote}”
              </p>
              <button
                type="button"
                onClick={() => {
                  setCompanionOpen(true);
                  prefillInputRef.current?.("");
                }}
                className="shrink-0 rounded-lg bg-[var(--primary)] px-2.5 py-1 text-[10.5px] font-semibold text-[var(--primary-foreground)]"
              >
                {t("Ask AI")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelection(null);
                  setReadingViewport({ selection: "" });
                }}
              >
                <X size={11} />
              </button>
            </div>
          )}
        </section>

        {showResizeHandle && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("Resize reading companion")}
            onPointerDown={startCompanionResize}
            className="group/resize relative z-10 hidden cursor-col-resize xl:block"
          >
            <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[var(--border)] transition-colors group-hover/resize:bg-[var(--primary)] group-active/resize:bg-[var(--primary)]" />
          </div>
        )}

        {companionOpen && (
          <ReadingCompanion
            workspaceId={workspaceId}
            material={activeTab?.material ?? null}
            conversations={conversations}
            activeConversation={activeConversation}
            linkedSessionIds={linkedSessionIds}
            activeLocator={activeLocator}
            selection={selection}
            onClearSelection={() => setSelection(null)}
            onOpenLinker={() => setShowLinker(true)}
            onSelectConversation={openConversation}
            onNewConversation={newConversation}
            onRenameConversation={setRenameConversationTarget}
            onDeleteConversation={setDeleteConversationTarget}
            onQuickPrompt={sendQuickPrompt}
            prefillInputRef={prefillInputRef}
            onClose={() => setCompanionOpen(false)}
          />
        )}
      </div>

      {removeTarget && (
        <WorkspaceConfirmDialog
          title={t("Remove from collection")}
          body={t(
            "Remove “{{title}}” from this collection? It stays in your library.",
            { title: removeTarget.title },
          )}
          actionLabel={t("Remove")}
          onClose={() => setRemoveTarget(null)}
          onConfirm={async () => {
            await removeMaterial(removeTarget);
            setRemoveTarget(null);
          }}
        />
      )}

      {renameConversationTarget && (
        <WorkspaceValueDialog
          title={t("Rename conversation")}
          label={t("Conversation name")}
          initialValue={renameConversationTarget.title}
          actionLabel={t("Save")}
          onClose={() => setRenameConversationTarget(null)}
          onSubmit={async (value) => {
            await renameConversation(
              renameConversationTarget.session_id,
              value,
            );
            setRenameConversationTarget(null);
          }}
        />
      )}

      {deleteConversationTarget && (
        <WorkspaceConfirmDialog
          title={t("Delete conversation")}
          body={t("Delete “{{title}}”? The transcript cannot be recovered.", {
            title: deleteConversationTarget.title,
          })}
          actionLabel={t("Delete")}
          onClose={() => setDeleteConversationTarget(null)}
          onConfirm={async () => {
            await deleteConversation(deleteConversationTarget.session_id);
            setDeleteConversationTarget(null);
          }}
        />
      )}

      {showRename && (
        <WorkspaceValueDialog
          title={t("Rename collection")}
          label={t("Collection name")}
          initialValue={workspace.title}
          actionLabel={t("Save")}
          onClose={() => setShowRename(false)}
          onSubmit={async (value) => {
            await renameWorkspace(value);
            setShowRename(false);
          }}
        />
      )}

      {showMastery && (
        <WorkspaceValueDialog
          title={t("Build Mastery Path")}
          label={t("Choose a Mastery Path ID for this collection")}
          initialValue={`reading-${workspace.workspace_id.slice(0, 8)}`}
          actionLabel={t("Build Mastery Path")}
          onClose={() => setShowMastery(false)}
          onSubmit={async (value) => {
            await buildMasteryPath(value);
            setShowMastery(false);
          }}
        />
      )}

      {showAddSource && (
        <AddMaterialsDialog
          mode="add"
          workspaceId={workspace.workspace_id}
          onClose={() => setShowAddSource(false)}
          onDone={({ workspace: updated }) => {
            if (updated) setWorkspace(updated);
            setShowAddSource(false);
          }}
        />
      )}

      {showLinker && activeConversation && (
        <ConversationLinkDialog
          conversations={conversations}
          current={activeConversation}
          onClose={() => setShowLinker(false)}
          onSave={async (ids) => {
            for (const id of ids) {
              if (!linkedSessionIds.includes(id)) {
                await linkReadingConversation(
                  workspaceId,
                  activeConversation.session_id,
                  id,
                );
              }
            }
            for (const id of linkedSessionIds) {
              if (!ids.includes(id)) {
                await unlinkReadingConversation(
                  workspaceId,
                  activeConversation.session_id,
                  id,
                );
              }
            }
            setConversations(await listReadingConversations(workspaceId));
            setShowLinker(false);
          }}
        />
      )}

      {showNotebook && (
        <NotebookCaptureDialog
          workspaceId={workspaceId}
          onClose={() => setShowNotebook(false)}
          onSaved={() => {
            setShowNotebook(false);
            setNotice(t("Reading notes sent to Notebook."));
          }}
        />
      )}

      {organizedNotes && (
        <OrganizedNotesDialog
          notes={organizedNotes}
          onClose={() => setOrganizedNotes(null)}
        />
      )}
    </main>
  );
}
