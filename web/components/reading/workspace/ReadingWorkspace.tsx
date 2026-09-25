"use client";

import { scopedUrl } from "@/lib/workspace-scope";
import { READING_HOME, readingFolderRoute, readingSessionIdFromPath } from "@/lib/learning-routes";

import { browserStorage } from "@/shared/storage";

import Link from "next/link";
import dynamic from "next/dynamic";
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import {
  ArrowLeft,
  CircleAlert,
  Expand,
  GraduationCap,
  Loader2,
  Minimize2,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  SquarePen,
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
import { consumePendingPrompt } from "@/lib/pending-prompt";
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
  listReadingConversations,
  retryReadingMaterial,
  unlinkReadingConversation,
  type ReadingLibraryMaterial,
} from "@/lib/reading-workspace-api";
import { SourceNavigator } from "./SourceNavigator";
import {
  EmptyWorkspace,
  MaterialFailure,
  MaterialProcessing,
} from "./WorkspaceChrome";
import {
  ConversationLinkDialog,
  NotebookCaptureDialog,
  OrganizedNotesDialog,
  WorkspaceConfirmDialog,
  WorkspaceValueDialog,
} from "./dialogs";
import { ReadingCompanion } from "./ReadingCompanion";
import { PageToolButtons, ReadAloudButton } from "./ReadAloudButton";
import {
  WorkspaceMenuContext,
  type WorkspaceMenuItem,
} from "@/components/reading/workspace-menu-context";
import { WorkspaceMenu, useWorkspaceMenuHost } from "./WorkspaceMenu";
import { useReadingWorkspace } from "./useReadingWorkspace";
import { useReadingLearningMode } from "./useLearningMode";

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
    navigatorOpen,
    openLearning,
    setCompanionOpen,
    setNavigatorOpen,
  } = useReadingLearningMode(workspaceId);
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
      if (open && !window.matchMedia("(min-width: 1024px)").matches) {
        setCompanionOpen(false);
      }
      setNavigatorOpen(open);
    },
    [setCompanionOpen, setNavigatorOpen],
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

  const startCompanionResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = companionWidth;
      const reserved = navigatorOpen ? 650 : 420;
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
    [companionWidth, navigatorOpen],
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

  // At desktop width the companion column is drag-resizable, so its track is
  // driven by JS state rather than the Tailwind classes below — a narrow
  // hairline "handle" track sits between the reader and the companion only
  // in this case. The navigator has no grid track when it is closed.
  const showResizeHandle = isDesktopWide && companionOpen;
  const gridStyle: React.CSSProperties | undefined = showResizeHandle
    ? {
        gridTemplateColumns: navigatorOpen
          ? `minmax(184px,230px) minmax(360px,1fr) 5px ${companionWidth}px`
          : `minmax(360px,1fr) 5px ${companionWidth}px`,
      }
    : undefined;

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
      className="reading-v2 flex h-full min-h-0 flex-col overflow-hidden bg-[var(--background)] text-[var(--foreground)] dark:bg-[var(--background)] dark:text-[var(--foreground)]"
    >
      <header className="flex h-11 shrink-0 items-center gap-1.5 border-b border-[var(--border)] bg-[var(--card)] px-2.5">
        <Link
          href={readingFolderRoute(workspace.workspace_id)}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
          aria-label={t("Back to folder")}
        >
          <ArrowLeft size={14} />
        </Link>
        {/* The outline opens on the left, so its switch lives on the left:
            it sat at the far right, next to the companion's, and a learner
            had to guess which of two panel icons was which. */}
        <button
          type="button"
          onClick={() => toggleNavigator(!navigatorOpen)}
          className={`flex size-7 shrink-0 items-center justify-center rounded-md transition hover:bg-[var(--muted)] ${
            navigatorOpen
              ? "text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          }`}
          aria-label={
            navigatorOpen ? t("Collapse contents") : t("Expand contents")
          }
          title={navigatorOpen ? t("Collapse contents") : t("Expand contents")}
          aria-expanded={navigatorOpen}
        >
          {navigatorOpen ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
        </button>
        <button
          type="button"
          onClick={() => setShowRename(true)}
          className="max-w-[240px] shrink-0 truncate font-serif text-[13.5px] font-semibold tracking-[-0.01em] transition hover:text-[var(--primary)]"
          title={t("Rename collection")}
        >
          {workspace.title}
        </button>
        <button
          type="button"
          onClick={() => setShowAddSource(true)}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--primary)]"
          aria-label={t("Add material")}
          title={t("Add material")}
        >
          <Plus size={14} />
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {notice && (
            <span className="hidden max-w-[220px] truncate px-2 text-[10px] text-[var(--muted-foreground)] 2xl:inline">
              {notice}
            </span>
          )}
          <ReadAloudButton disabled={!materialReady} />
          <PageToolButtons
            disabled={!materialReady || state.isStreaming}
            onQuiz={quizThisPage}
          />
          {/* An icon, like every other control on this bar: as the only
              labelled button it read as the page's primary action. */}
          <button
            type="button"
            onClick={() => (learning ? closeLearning() : openLearning())}
            className={`flex size-7 shrink-0 items-center justify-center rounded-md transition hover:bg-[var(--muted)] ${
              learning
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
            aria-pressed={learning}
            aria-label={t(
              learning ? "Exit learning mode" : "Fullscreen learning",
            )}
            title={t(
              learning ? "Exit learning mode" : "Fullscreen learning",
            )}
          >
            {learning ? <Minimize2 size={14} /> : <Expand size={14} />}
          </button>
          <WorkspaceMenu
            sections={menuSections}
            collection={collectionMenu}
          />
          {/* Past conversations are in the app sidebar with every other one;
              this bar only starts a fresh one. Beside the companion's switch,
              since that is the column it clears. */}
          <button
            type="button"
            onClick={newConversation}
            disabled={!activeConversation}
            className="flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            aria-label={t("New conversation")}
            title={t("New conversation")}
          >
            <SquarePen size={14} />
          </button>
          <button
            type="button"
            onClick={() => toggleCompanion(!companionOpen)}
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
            ? navigatorOpen
              ? "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)] xl:grid-cols-[minmax(184px,230px)_minmax(360px,1fr)_5px_minmax(330px,420px)]"
              : "grid-cols-[minmax(0,1fr)] xl:grid-cols-[minmax(360px,1fr)_5px_minmax(330px,420px)]"
            : navigatorOpen
              ? "grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(184px,230px)_minmax(0,1fr)]"
              : "grid-cols-[minmax(0,1fr)]"
        }`}
        style={gridStyle}
      >
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
              />
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
            activeConversation={activeConversation}
            linkedSessionIds={linkedSessionIds}
            activeLocator={activeLocator}
            selection={selection}
            onClearSelection={() => setSelection(null)}
            onOpenLinker={openLinker}
            prefillInputRef={prefillInputRef}
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
    </WorkspaceMenuContext.Provider>
    </ReadingActionsProvider>
  );
}
