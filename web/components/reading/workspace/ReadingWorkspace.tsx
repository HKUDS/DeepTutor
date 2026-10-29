"use client";

import { scopedUrl } from "@/lib/workspace-scope";
import { READING_HOME, readingFolderRoute, readingSessionIdFromPath } from "@/lib/learning-routes";

import Link from "next/link";
import dynamic from "next/dynamic";
import {
  useParams,
  usePathname,
  useRouter,
} from "next/navigation";
import {
  CircleAlert,
  GraduationCap,
  Loader2,
  NotebookPen,
  StickyNote,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { JumpRequest } from "@/components/reading/PdfDocumentView";
import { READER_ASK_EVENT, ReaderPane } from "@/components/reading/ReaderPane";
import { ReadingActionsProvider } from "@/components/reading/ReadingActionsProvider";
import { focusReadingComposer } from "@/components/reading/reading-actions-context";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import type { ReaderHeading } from "@/lib/reading-outline";
import { setReadingViewport } from "@/lib/reading-turn-state";
import { workspaceActionNeedsConfiguration } from "@/lib/workspace-mode";
import {
  PAGE_QUIZ_CAPABILITY,
  PAGE_QUIZ_CONFIG,
} from "@/lib/reading-passage-prompts";
import {
  getMaterial,
  getUnitText,
  rawMaterialUrl,
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
  retryReadingMaterial,
  unlinkReadingConversation,
  type ReadingLibraryMaterial,
} from "@/lib/reading-workspace-api";
import { SourceNavigator } from "./SourceNavigator";
import { ReadingPanelSeparator } from "./ReadingPanelSeparator";
import { useReadingPanelLayout } from "./useReadingPanelLayout";
import {
  EmptyWorkspace,
  MaterialFailure,
  MaterialProcessing,
} from "./WorkspaceChrome";
import { ReadingCompanion } from "./ReadingCompanion";
import { CompanionHead, ReadingBar } from "./ReadingBar";
import {
  WorkspaceMenuContext,
  type WorkspaceMenuItem,
} from "@/components/reading/workspace-menu-context";
import { useWorkspaceMenuHost } from "./WorkspaceMenu";
import { useReadingWorkspace } from "./useReadingWorkspace";
import { useReadingLearningMode } from "./useLearningMode";

// Dialogs are only needed after an explicit workspace action.
const ConversationLinkDialog = dynamic(
  () => import("./dialogs").then((module) => module.ConversationLinkDialog),
  { ssr: false },
);
const NotebookCaptureDialog = dynamic(
  () => import("./dialogs").then((module) => module.NotebookCaptureDialog),
  { ssr: false },
);
const OrganizedNotesDialog = dynamic(
  () => import("./dialogs").then((module) => module.OrganizedNotesDialog),
  { ssr: false },
);
const WorkspaceConfirmDialog = dynamic(
  () => import("./dialogs").then((module) => module.WorkspaceConfirmDialog),
  { ssr: false },
);
const WorkspaceValueDialog = dynamic(
  () => import("./dialogs").then((module) => module.WorkspaceValueDialog),
  { ssr: false },
);

const MediaReadingStage = dynamic(
  () => import("./MediaReadingStage").then((module) => module.MediaReadingStage),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={24} className="animate-spin text-[var(--primary)]" />
      </div>
    ),
  },
);
const AddMaterialsDialog = dynamic(
  () =>
    import("@/components/reading/library/AddMaterialsDialog").then(
      (module) => module.AddMaterialsDialog,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--overlay)]">
        <Loader2 size={24} className="animate-spin text-[var(--primary)]" />
      </div>
    ),
  },
);

interface ReaderAskDetail {
  quote?: string;
  locator?: number;
  unit?: string;
  /** Send this about the passage now, instead of waiting for a question. */
  prompt?: string;
}

export function ReadingWorkspacePage() {
  const params = useParams<{ workspaceId: string }>();
  const workspaceId = params.workspaceId;
  // From the path, not from route params: the first turn binds its session id
  // with the native history API so the workspace is not torn down mid-answer,
  // and `useParams` does not follow that — `usePathname` does.
  const sessionIdParam = readingSessionIdFromPath(usePathname());
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
    refreshConversations,
    setNotice,
    material,
    annotations,
    activeTab,
    activeConversation,
    linkedSessionIds,
    activeLocator,
    setActiveLocator,
    bookmarks,
    toggleBookmark,
    removeBookmark,
    transcript,
    organizedNotes,
    setOrganizedNotes,
    refresh,
    switchMaterial,
    removeMaterial,
    newConversation,
    organizeNotes,
    buildMasteryPath,
    renameWorkspace,
    reportViewport,
  } = useReadingWorkspace(workspaceId, sessionIdParam);

  // View-only state: what the reader is pointing at and which panels are open.
  const [transcriptSearch, setTranscriptSearch] = useState("");
  const [selection, setSelection] = useState<{
    quote: string;
    locator: number;
  } | null>(null);
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
  const [isDesktopWide, setIsDesktopWide] = useState(false);
  // The bar's place for the open document's title row (see ReaderPane).
  const [docSlot, setDocSlot] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1280px)");
    const update = () => setIsDesktopWide(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  const [showSessions, setShowSessions] = useState(false);
  const [showLinker, setShowLinker] = useState(false);
  // Stable: the companion hands it to the workspace ⋯ inside memoised items,
  // and a fresh arrow every render re-registered them forever.
  const openLinker = useCallback(() => setShowLinker(true), []);
  const [showNotebook, setShowNotebook] = useState(false);
  const [showAddSource, setShowAddSource] = useState(false);
  const { host: menuHost, sections: menuSections } = useWorkspaceMenuHost();
  const [showRename, setShowRename] = useState(false);
  const [showMastery, setShowMastery] = useState(false);
  const collectionMenu = useMemo<WorkspaceMenuItem[]>(
    () => [
      {
        key: "organize",
        icon: StickyNote,
        label: t("Organize notes"),
        onSelect: () => void organizeNotes(),
      },
      {
        key: "notebook",
        icon: NotebookPen,
        label: t("Send to Notebook"),
        onSelect: () => setShowNotebook(true),
      },
      {
        key: "mastery",
        icon: GraduationCap,
        label: t("Build Mastery Path"),
        onSelect: () => setShowMastery(true),
      },
    ],
    [organizeNotes, t],
  );
  const [removeTarget, setRemoveTarget] =
    useState<ReadingLibraryMaterial | null>(null);
  const {
    closeLearning,
    companionOpen,
    learning,
    mainRef,
    navigatorOpen: preferredNavigatorOpen,
    openLearning,
    setCompanionOpen: setPreferredCompanionOpen,
    setNavigatorOpen,
  } = useReadingLearningMode(workspaceId);
  const { gridRef, ...panels } = useReadingPanelLayout({
    enabled: isDesktopWide,
    navigatorOpen: preferredNavigatorOpen,
    companionOpen,
  });
  const { navigatorOpen, exitFocus } = panels;
  const companionDocked = isDesktopWide && companionOpen;
  const setCompanionOpen = useCallback(
    (open: boolean) => {
      if (!open) exitFocus();
      setPreferredCompanionOpen(open);
    },
    [exitFocus, setPreferredCompanionOpen],
  );

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
  }, [setCompanionOpen]);

  // The two panels are independent wherever at least one of them docks:
  // opening one used to close the other at every width, so a learner could
  // never see the outline and the conversation together. Below `lg` both are
  // sheets over the document, and two sheets at once is just a mess.
  const toggleNavigator = useCallback(
    (open: boolean) => {
      exitFocus();
      if (open && !window.matchMedia("(min-width: 1024px)").matches) {
        setCompanionOpen(false);
      }
      setNavigatorOpen(open);
    },
    [exitFocus, setCompanionOpen, setNavigatorOpen],
  );
  const toggleCompanion = useCallback(
    (open: boolean) => {
      if (open && !window.matchMedia("(min-width: 1024px)").matches) {
        setNavigatorOpen(false);
      }
      setCompanionOpen(open);
    },
    [setCompanionOpen, setNavigatorOpen],
  );

  useEffect(() => {
    const onAsk = (event: Event) => {
      const detail = (event as CustomEvent<ReaderAskDetail>).detail;
      const quote = String(detail?.quote ?? "").trim();
      if (!quote) return;
      const locator = Number(detail.locator || activeLocator);
      const prompt = String(detail?.prompt ?? "").trim();
      toggleCompanion(true);
      // Explain / translate / guide: a message in this conversation, sent
      // now, with the passage attached the same way a typed question gets it.
      // A turn still streaming, or a mode that wants its settings confirmed
      // first, gets the passage and the words in the box instead of a send
      // that would be refused or would run the wrong mode.
      if (
        prompt &&
        !state.isStreaming &&
        !workspaceActionNeedsConfiguration(state.activeCapability)
      ) {
        setReadingViewport({ locator, selection: quote });
        sendMessage(prompt, undefined, undefined, undefined, linkedSessionIds);
        setSelection(null);
        window.setTimeout(() => setReadingViewport({ selection: "" }), 0);
        return;
      }
      setSelection({ quote, locator });
      setReadingViewport({ locator, selection: quote });
      if (prompt) {
        window.requestAnimationFrame(() => prefillInputRef.current?.(prompt));
        return;
      }
      // Focus, not `prefillInputRef("")`: that one *sets* the text, and
      // "Ask about this" used to wipe whatever the learner had half-typed.
      // A frame later, because a closed companion is not mounted yet.
      window.requestAnimationFrame(focusReadingComposer);
    };
    window.addEventListener(READER_ASK_EVENT, onAsk);
    return () => window.removeEventListener(READER_ASK_EVENT, onAsk);
  }, [
    activeLocator,
    linkedSessionIds,
    sendMessage,
    state.activeCapability,
    state.isStreaming,
    toggleCompanion,
  ]);

  // "Quiz me": a quiz turn in this conversation, run by the same engine as
  // the composer's Quiz mode, with its settings chosen here instead of asked
  // for. The conversation's own mode is left as it was.
  const quizThisPage = useCallback(() => {
    if (state.isStreaming) return;
    toggleCompanion(true);
    setReadingViewport({ locator: activeLocator, selection: "" });
    sendMessage(
      t("Quiz me on this page"),
      undefined,
      { ...PAGE_QUIZ_CONFIG },
      undefined,
      linkedSessionIds,
      { capability: PAGE_QUIZ_CAPABILITY },
    );
  }, [
    activeLocator,
    linkedSessionIds,
    sendMessage,
    state.isStreaming,
    t,
    toggleCompanion,
  ]);

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
          href={scopedUrl(READING_HOME)}
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

  // Panels below their docking width are sheets over the document, and a
  // sheet needs a scrim to close it by. The navigator docks at `lg`, the
  // companion at `xl`; the scrim used to key on either one being open with a
  // single `xl:hidden`, so at `lg` it dimmed a document the docked navigator
  // was sitting beside and swallowed every click on the page.
  const scrimClass =
    companionOpen ? "xl:hidden" : navigatorOpen ? "lg:hidden" : "";
  const materialReady =
    activeTab?.material.status === "ready" && !isMedia && Boolean(material);

  return (
    <ReadingActionsProvider
      materialId={materialReady ? (activeTab?.material.material_id ?? null) : null}
      locator={activeLocator}
      onStart={() => toggleCompanion(true)}
    >
    <WorkspaceMenuContext.Provider value={menuHost}>
    <main
      ref={mainRef}
      data-learning={learning ? "true" : undefined}
      data-reading-workspace=""
      className="reading-v2 dt-reading-desk flex h-full min-h-0 flex-col overflow-hidden bg-[var(--background)] text-[var(--foreground)] dark:bg-[var(--background)] dark:text-[var(--foreground)]"
    >

      {/* One desk: the bar sits over the document columns only, and a docked
          companion runs the full height beside them as a sheet of its own. */}
      <div
        ref={gridRef}
        className={`relative grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${
          companionOpen
            ? navigatorOpen
              ? "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)] xl:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)_5px_minmax(330px,420px)]"
              : "grid-cols-[minmax(0,1fr)] xl:grid-cols-[minmax(360px,1fr)_5px_minmax(330px,420px)]"
            : navigatorOpen
              ? "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(0,1fr)]"
              : "grid-cols-[minmax(0,1fr)]"
        }`}
        style={panels.gridStyle}
      >
        <div className={`min-w-0 ${companionDocked ? "[grid-column:1/-3]" : "col-span-full"}`}>
          <ReadingBar
            backHref={readingFolderRoute(workspace.workspace_id)}
            collectionId={workspace.workspace_id}
            title={workspace.title}
            onRename={() => setShowRename(true)}
            onAdd={() => setShowAddSource(true)}
            documents={workspace.tabs}
            activeDocumentId={activeTab?.material.material_id ?? null}
            onSwitchDocument={(tab) => void switchMaterial(tab.material)}
            navigatorOpen={navigatorOpen}
            onToggleNavigator={() => toggleNavigator(!navigatorOpen)}
            docSlot={setDocSlot}
            notice={notice}
            materialReady={materialReady}
            busy={state.isStreaming}
            onQuiz={quizThisPage}
            learning={learning}
            onToggleLearning={() => (learning ? closeLearning() : openLearning())}
            menuSections={menuSections}
            collection={collectionMenu}
            companionOpen={companionOpen}
            onOpenCompanion={() => toggleCompanion(true)}
          />
        </div>
        {scrimClass && (
          <button
            type="button"
            className={`absolute inset-0 z-20 bg-[var(--overlay)] ${scrimClass}`}
            onClick={() => {
              // Only the panels that are sheets at this width: a docked
              // navigator has nothing to do with a tap on the scrim.
              if (!window.matchMedia("(min-width: 1024px)").matches) {
                setNavigatorOpen(false);
              }
              setCompanionOpen(false);
            }}
            aria-label={t("Close panels")}
          />
        )}
        <SourceNavigator
          material={activeTab?.material ?? null}
          materials={workspace.tabs}
          activeMaterialId={workspace.active_material_id}
          onSelectMaterial={(candidate) => void switchMaterial(candidate)}
          onRemoveMaterial={setRemoveTarget}
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
          bookmarks={bookmarks}
          onRemoveBookmark={(bookmarkId) => void removeBookmark(bookmarkId)}
          onOpenAnnotation={(locator, quote) =>
            setDocumentJump((current) => ({
              locator,
              quote,
              nonce: (current?.nonce ?? 0) + 1,
            }))
          }
          annotationCount={annotations.length}
          unitCount={material?.unit_count ?? 0}
          open={navigatorOpen}
          onClose={() => setNavigatorOpen(false)}
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

        {panels.showNavigatorHandle && (
          <ReadingPanelSeparator
            label={t("Resize contents navigator")}
            width={panels.navigatorWidth}
            min={panels.navigatorMin}
            max={panels.navigatorMax}
            direction={1}
            onResize={panels.resizeNavigator}
            className="row-start-2"
          />
        )}

        <section className="dt-reading-canvas relative row-start-2 min-h-0 min-w-0 overflow-hidden bg-[var(--secondary)]">
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
              transcript={material?.unit === "segment" ? transcript : []}
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
                // The outline highlights the row the reader is inside, so it
                // has to hear about pages turned in the document and not only
                // about rows clicked in the panel. ReaderPane reports its own
                // viewport, unlike the media stage above.
                onLocatorChange={setActiveLocator}
                headingJump={headingJump}
                ownAnnotationList={false}
                bookmarks={bookmarks}
                onToggleBookmark={(locator, label) =>
                  void toggleBookmark(locator, label)
                }
                onClose={() => router.push(scopedUrl(READING_HOME))}
                headSlot={docSlot}
              />
            </div>
          )}

        </section>

        {panels.showCompanionHandle && (
          <ReadingPanelSeparator
            label={t("Resize reading companion")}
            width={panels.companionWidth}
            min={panels.companionMin}
            max={panels.companionMax}
            direction={-1}
            onResize={panels.resizeCompanion}
            className="row-span-2 row-start-1 [grid-column:-3/-2]"
          />
        )}

        {companionOpen && (
          <ReadingCompanion
            workspaceId={workspaceId}
            material={activeTab?.material ?? null}
            activeConversation={activeConversation}
            linkedSessionIds={linkedSessionIds}
            activeLocator={activeLocator}
            selection={selection}
            onClearSelection={() => setSelection(null)}
            onOpenLinker={openLinker}
            prefillInputRef={prefillInputRef}
            head={
              <CompanionHead
                title={activeConversation?.title}
                canStartOver={Boolean(activeConversation)}
                onStartOver={newConversation}
                focus={isDesktopWide ? { active: panels.companionFocus, toggle: panels.toggleFocus } : undefined}
                onClose={() => toggleCompanion(false)}
              />
            }
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
            await refreshConversations();
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
    </WorkspaceMenuContext.Provider>
    </ReadingActionsProvider>
  );
}
