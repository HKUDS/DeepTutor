"use client";

import { navigateTask } from "@/lib/workspace-scope";
import Image from "next/image";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  Suspense,
  type ReactNode,
  type CSSProperties,
} from "react";
import { useAppShell } from "@/context/AppShellContext";
import { ChevronsLeft, ChevronsRight, PanelLeftClose, Search, SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useChatWorkspaces } from "@/hooks/useChatWorkspaces";

import { useSidebarDrawer } from "@/components/layout/AppShell";
import { useDevice } from "@/hooks/useDevice";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import { isNoteSession } from "@/lib/mastery-session";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { CategoryBody, CategoryTabs, useCategoryNavigation } from "@/components/sidebar/CategoryNavigation";
import { isLearningSession } from "@/lib/navigation";
import Tooltip from "@/shared/ui/Tooltip";
import { WorkspaceMenu } from "@/components/sidebar/WorkspaceMenu";
import { SHORTCUTS, matchesShortcut } from "@/lib/shortcuts";
import { RecordHeader, useRecordView } from "@/components/sidebar/RecordList";
import type { LearningSessions } from "@/components/sidebar/LearningNavigation";

// The fallback history list is needed only by shells without organization.
const SessionList = dynamic(() => import("@/components/SessionList"), { ssr: false });

// Loaded on first ⌘K, with the learning and partner indexes it searches.
const CommandPalette = dynamic(
  () => import("@/components/sidebar/CommandPalette").then((module) => module.CommandPalette),
  { ssr: false },
);

// Session data arrives after mount; defer its organization UI with it so
// every workspace route does not download it as part of the initial shell.
const OrganizedSessionList = dynamic(
  () => import("@/components/sessions/OrganizedSessionList"),
  {
    ssr: false,
    loading: () => (
      <div aria-busy="true" className="space-y-1.5 px-2 py-1">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-4 w-3/4 animate-pulse rounded bg-muted/40"
          />
        ))}
      </div>
    ),
  },
);

export interface SidebarShellProps {
  /** Reuse the shell's resizing/collapse behavior with embedded navigation. */
  homeSlot?: (collapsed: boolean) => ReactNode;
  bodySlot?: (collapsed: boolean) => ReactNode;
  footerOverride?: (collapsed: boolean) => ReactNode;
  brandHref?: string;
  initialWidth?: number;
  widthStorageKey?: string;
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
  /** Conversations the caller is streaming right now; they sort to the top. */
  liveSessionIds?: ReadonlySet<string>;
  loadingSessions?: boolean;
  showSessions?: boolean;
  /** Clicking the Chat nav item resets to a fresh session via this handler. */
  onNewChat?: () => void;
  onSelectSession?: (sessionId: string) => void | Promise<void>;
  onRenameSession?: (sessionId: string, title: string) => void | Promise<void>;
  onDeleteSession?: (sessionId: string) => void | Promise<void>;
  /** Topic labels for grouping mastery study conversations under their path. */
  masteryTopics?: MasteryTopicLabel[];
  /** Collection labels for grouping reading conversations under their shelf. */
  readingCollections?: ReadingCollectionLabel[];
  onOrganizeSession?: (
    sessionId: string,
    patch: SessionOrganizationPatch,
  ) => void | Promise<void>;
  /**
   * Footer content rendered below the nav. Pass a render function to receive
   * the current ``collapsed`` state so footer items (e.g. Admin / Sign out) can
   * switch to their icon-only variant when the rail is collapsed.
   */
  footerSlot?: ReactNode | ((collapsed: boolean) => ReactNode);
}

export function SidebarShell({
  homeSlot,
  bodySlot,
  footerOverride,
  brandHref = "/",
  initialWidth = 272,
  widthStorageKey,
  sessions = [],
  activeSessionId = null,
  liveSessionIds,
  loadingSessions = false,
  showSessions = false,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  masteryTopics = [],
  readingCollections = [],
  onOrganizeSession,
  footerSlot,
}: SidebarShellProps) {
  const categoryNav = useCategoryNavigation();
  const router = useRouter();
  const { t } = useTranslation();
  const { sidebarCollapsed, setSidebarCollapsed: setCollapsed } = useAppShell();
  const { isMobile } = useDevice();
  const drawer = useSidebarDrawer();
  const recentsScrollRef = useRef<HTMLDivElement>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The row menus offer these as move destinations.
  const { workspaces } = useChatWorkspaces();

  // Inside the mobile drawer the icon-only rail is pointless — the panel is
  // already hidden when you don't want it, so it always opens fully expanded
  // regardless of the persisted desktop preference.
  const collapsed = sidebarCollapsed && !isMobile;
  const resize = useSidebarResize(collapsed || isMobile, initialWidth, widthStorageKey);

  // The account links live in the workspace menu, which always shows them in
  // full, open sidebar or rail.
  const renderedFooter =
    typeof footerSlot === "function" ? footerSlot(false) : footerSlot;
  // Conversations read like the learning and partner records: by day, in
  // the order the learner picked, searchable in place.
  const chatView = useRecordView("deeptutor.navigation.chats.sort");

  const startNewChat = () => {
    drawer?.close();
    onNewChat?.();
    navigateTask("/chat", router.push);
  };

  const handleHomeClick = (event: React.MouseEvent) => {
    // Always reset to a fresh session (mirrors the old "New Chat" affordance);
    // let modifier-clicks fall through to default Link behavior so middle-click
    // open-in-new-tab still works.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    event.preventDefault();
    startNewChat();
  };

  // Shell shortcuts. The handler is re-bound after every render so it always
  // sees the current category list; the listener itself is installed once.
  const hotkeys = useRef<(event: KeyboardEvent) => void>(() => {});
  const handleHotkey = (event: KeyboardEvent) => {
    if (matchesShortcut(event, SHORTCUTS.search)) {
      event.preventDefault();
      setPaletteOpen((open) => !open);
    } else if (matchesShortcut(event, SHORTCUTS.newChat)) {
      event.preventDefault();
      startNewChat();
    } else {
      const index = categoryNav.categories.findIndex((_, position) =>
        matchesShortcut(event, SHORTCUTS.category(position)),
      );
      if (index < 0) return;
      event.preventDefault();
      const target = categoryNav.categories[index];
      categoryNav.select(target.id);
      if (collapsed) navigateTask(target.href, router.push);
    }
  };
  useLayoutEffect(() => {
    hotkeys.current = handleHotkey;
  });
  useEffect(() => {
    if (bodySlot) return;
    const onKeyDown = (event: KeyboardEvent) => hotkeys.current(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [bodySlot]);

  const palette =
    !bodySlot && paletteOpen ? (
      <CommandPalette
        open
        onClose={() => setPaletteOpen(false)}
        categories={categoryNav.categories}
        allowedSurfaces={categoryNav.allowedSurfaces}
        sessions={sessions}
        onSelectSession={onSelectSession}
        onNewChat={startNewChat}
      />
    ) : null;

  // Everything the learner has, minus the archived and minus the tutor threads
  // that render nested under the conversation that spawned them.
  //
  // Keep the complete index here. OrganizedSessionList limits the initial
  // rendering and exposes older conversations through Show more.
  // The product shell files learning conversations under Learning only; an
  // embedded body (the /preview demo) brings its own lists.
  const listed = sessions.filter(
    (session) =>
      !session.preferences?.archived &&
      !session.preferences?.parent_session_id &&
      !isNoteSession(session),
  );
  const visibleSessions = bodySlot ? listed : listed.filter((session) => !isLearningSession(session));

  // Learning conversations are filed under the record they were held in; the
  // learning shelf draws them with the same rows and actions as these.
  const learningSessions: LearningSessions | undefined =
    !bodySlot && showSessions && onSelectSession && onRenameSession && onDeleteSession && onOrganizeSession
      ? {
          rows: listed.filter(isLearningSession),
          activeSessionId,
          render: (rows) => (
            <OrganizedSessionList
              sessions={rows}
              workspaces={workspaces}
              nested={false}
              times
              activeSessionId={activeSessionId}
              liveSessionIds={liveSessionIds}
              onSelect={(sessionId) => {
                drawer?.close();
                return onSelectSession(sessionId);
              }}
              onRename={onRenameSession}
              onDelete={onDeleteSession}
              onOrganize={onOrganizeSession}
            />
          ),
        }
      : undefined;

  // Conversation history follows the category's entries in the same scroller.
  const sessionContent = (
    <>
      {showSessions &&
      onSelectSession &&
      onRenameSession &&
      onDeleteSession &&
      onOrganizeSession ? (
        <section className="dt-navigation-section dt-session-section">
          <RecordHeader
            title={t("navigation.chatRecords")}
            count={loadingSessions ? undefined : visibleSessions.length}
            view={chatView}
            searchLabel={t("navigation.searchChats")}
          />
          {loadingSessions ? (
            <SessionList
              sessions={[]}
              activeSessionId={activeSessionId}
              loading
              onSelect={onSelectSession}
              onRename={onRenameSession}
              onDelete={onDeleteSession}
              compact
            />
          ) : (
            <OrganizedSessionList
              sessions={visibleSessions}
              workspaces={workspaces}
              timeline={chatView}
              masteryTopics={masteryTopics}
              readingCollections={readingCollections}
              activeSessionId={activeSessionId}
              liveSessionIds={liveSessionIds}
              onSelect={(sessionId) => {
                drawer?.close();
                return onSelectSession(sessionId);
              }}
              onRename={onRenameSession}
              onDelete={onDeleteSession}
              onOrganize={onOrganizeSession}
            />
          )}
        </section>
      ) : null}
    </>
  );

  /* ---- Collapsed state ---- */
  if (collapsed) {
    return (
      <aside className={`${bodySlot ? "" : "dt-product-sidebar"} dt-rail relative flex h-dvh w-[60px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 transition-all duration-200`}>
        {/* The open sidebar's header, stood on end: the workspace (with its
            menu of settings and account), the way back out, then search. */}
        {bodySlot ? (
          <Link href={brandHref} prefetch={false} aria-label="DeepTutor" className="dt-rail-brand">
            <Image src="/brand/color-logo.png" alt="DeepTutor" width={22} height={22} className="h-[22px] w-[22px] rounded-md" />
          </Link>
        ) : (
          <WorkspaceMenu compact accountSlot={renderedFooter} onNavigate={() => drawer?.close()} />
        )}
        <Tooltip label={t("Expand sidebar")} side="right">
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            className="dt-nav-icon"
            aria-label={t("Expand sidebar")}
          >
            <ChevronsRight size={17} strokeWidth={1.6} />
          </button>
        </Tooltip>
        <div aria-hidden className="dt-rail-divider" />
        {!bodySlot && (
          <Tooltip label={t("navigation.search")} side="right" shortcut={SHORTCUTS.search}>
            <button
              type="button"
              className="dt-nav-icon"
              aria-label={t("navigation.search")}
              aria-haspopup="dialog"
              onClick={() => setPaletteOpen(true)}
            >
              <Search size={17} strokeWidth={1.6} />
            </button>
          </Tooltip>
        )}

        {homeSlot ? homeSlot(true) : <CategoryTabs nav={categoryNav} collapsed />}
        <div className="min-h-0 w-full flex-1 overflow-y-auto overscroll-contain">
          {bodySlot ? bodySlot(true) : <CategoryBody nav={categoryNav} collapsed sessions={null} />}
        </div>

        {footerOverride ? footerOverride(true) : (
          <div className="dt-rail-foot">
            <Tooltip label={t("navigation.newChat")} side="right" shortcut={SHORTCUTS.newChat}>
              <Link prefetch={false} href="/chat" onClick={handleHomeClick} aria-label={t("navigation.newChat")} className="dt-nav-icon">
                <SquarePen size={17} strokeWidth={1.6} />
              </Link>
            </Tooltip>
          </div>
        )}
        {palette}
      </aside>
    );
  }

  /* ---- Expanded state ---- */
  return (
    <aside
      style={{ "--sidebar-width": `${resize.width}px` } as CSSProperties}
      className={`${bodySlot ? "" : "dt-product-sidebar"} relative flex h-dvh w-[var(--sidebar-width)] max-w-[45vw] shrink-0 flex-col bg-[var(--secondary)] max-md:w-[220px] max-md:max-w-[85vw]`}
    >
      {bodySlot ? (
        <div className="flex h-[52px] shrink-0 items-center justify-between px-4">
          <Link href={brandHref} prefetch={false} className="group flex items-center gap-1.5">
            <Image
              src="/brand/color-logo.png"
              alt="DeepTutor"
              width={22}
              height={22}
              className="h-[22px] w-[22px] transition-transform duration-200 group-hover:scale-105"
            />
            <Image
              src="/brand/color-word.png"
              alt="DeepTutor"
              width={1200}
              height={310}
              priority
              className="h-[22px] w-auto transition-transform duration-200 group-hover:scale-105"
            />
          </Link>
          {/* The rail is a desktop affordance; in the drawer the scrim and the
              top-bar toggle already own "make this go away". */}
          <button
            onClick={() => setCollapsed(true)}
            className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] max-md:hidden"
            aria-label={t("Collapse sidebar")}
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      ) : (
        <div className="dt-sidebar-header">
          <WorkspaceMenu accountSlot={renderedFooter} onNavigate={() => drawer?.close()} />
          <Tooltip label={t("navigation.search")} side="bottom" shortcut={SHORTCUTS.search}>
            <button
              type="button"
              className="dt-nav-icon dt-sidebar-search"
              aria-label={t("navigation.search")}
              aria-haspopup="dialog"
              onClick={() => setPaletteOpen(true)}
            >
              <Search size={16} strokeWidth={1.7} />
            </button>
          </Tooltip>
          {/* The rail is a desktop affordance; in the drawer the scrim and the
              top-bar toggle already own "make this go away". */}
          <Tooltip label={t("Collapse sidebar")} side="bottom">
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              className="dt-nav-icon max-md:hidden"
              aria-label={t("Collapse sidebar")}
            >
              <ChevronsLeft size={17} strokeWidth={1.6} />
            </button>
          </Tooltip>
        </div>
      )}

      {homeSlot ? homeSlot(false) : <CategoryTabs nav={categoryNav} collapsed={false} />}

      {/* Partner previews stay visible while their conversation list scrolls. */}
      <div
        ref={recentsScrollRef}
        className={`min-h-0 flex-1 ${!bodySlot && ["partners", "learning"].includes(categoryNav.category) ? "overflow-hidden" : "overflow-y-auto overscroll-contain pb-2"}`}
      >
        <Suspense fallback={<div aria-busy="true" className="mx-4 mt-5 h-3 w-28 rounded bg-muted" />}>
          {bodySlot ? bodySlot(false) : <CategoryBody nav={categoryNav} collapsed={false} sessions={sessionContent} learningSessions={learningSessions} />}
        </Suspense>
      </div>

      {/* Secondary nav + footer */}
      {footerOverride ? footerOverride(false) : (
        <div className="dt-sidebar-footer">
          <Tooltip label={t("navigation.newChat")} side="top" shortcut={SHORTCUTS.newChat} as="div" className="block w-full">
            <Link prefetch={false} href="/chat" onClick={handleHomeClick} className="dt-new-conversation">
              <SquarePen size={16} strokeWidth={1.7} />
              <span>{t("navigation.newChat")}</span>
            </Link>
          </Tooltip>
        </div>
      )}
      {!isMobile && (
        <div
          role="separator"
          aria-label={t("Resize sidebar")}
          aria-orientation="vertical"
          aria-valuemin={resize.min}
          aria-valuemax={resize.max}
          aria-valuenow={resize.width}
          tabIndex={0}
          {...resize.handleProps}
          className="group/resize absolute inset-y-0 -right-1 z-30 w-2 touch-none cursor-col-resize outline-none max-md:hidden"
        >
          <div
            className={`mx-auto h-full w-0.5 transition-colors group-hover/resize:bg-[var(--ring)] group-focus-visible/resize:bg-[var(--ring)] ${resize.resizing ? "bg-[var(--ring)]" : "bg-transparent"}`}
          />
        </div>
      )}
      {palette}
    </aside>
  );
}
