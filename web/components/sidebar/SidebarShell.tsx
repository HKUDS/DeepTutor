"use client";

import { navigateTask } from "@/lib/workspace-scope";
import Image from "next/image";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type CSSProperties,
} from "react";
import { useAppShell } from "@/context/AppShellContext";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useChatWorkspaces } from "@/hooks/useChatWorkspaces";
import SessionList from "@/components/SessionList";
import { useSidebarDrawer } from "@/components/layout/AppShell";
import { useDevice } from "@/hooks/useDevice";
import { VersionBadge } from "@/components/sidebar/VersionBadge";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type { StudyCourse } from "@/lib/courses-api";
import { useSidebarResize } from "@/hooks/useSidebarResize";
import { SidebarHome, SidebarNav } from "@/components/sidebar/SidebarNav";
import { SECONDARY_NAV, isNavActive } from "@/components/sidebar/nav-entries";
import {
  mergeManualOrder,
  readSessionOrder,
  writeSessionOrder,
} from "@/lib/sidebar-layout";

// Session data arrives after mount; defer its organization UI with it so
// every workspace route does not download it as part of the initial shell.
const OrganizedSessionList = dynamic(
  () => import("@/components/courses/OrganizedSessionList"),
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

interface SidebarShellProps {
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
  /** Conversations the caller is streaming right now; they sort to the top. */
  liveSessionIds?: ReadonlySet<string>;
  loadingSessions?: boolean;
  showSessions?: boolean;
  /** Clicking the Chat nav item resets to a fresh session via this handler. */
  onNewChat?: () => void;
  onNewWorkspaceChat?: (workspaceId: string) => void;
  workspaceRefreshToken?: number;
  onSelectSession?: (sessionId: string) => void | Promise<void>;
  onRenameSession?: (sessionId: string, title: string) => void | Promise<void>;
  onDeleteSession?: (sessionId: string) => void | Promise<void>;
  courses?: StudyCourse[];
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
  sessions = [],
  activeSessionId = null,
  liveSessionIds,
  loadingSessions = false,
  showSessions = false,
  onNewChat,
  onNewWorkspaceChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  masteryTopics = [],
  readingCollections = [],
  onOrganizeSession,
  footerSlot,
}: SidebarShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const { sidebarCollapsed, setSidebarCollapsed: setCollapsed } = useAppShell();
  const { isMobile } = useDevice();
  const drawer = useSidebarDrawer();
  const recentsScrollRef = useRef<HTMLDivElement>(null);
  // One load for the whole column: the workspace groups head their own
  // section with it and the row menus offer it as a move destination.
  const { workspaces } = useChatWorkspaces();

  // Inside the mobile drawer the icon-only rail is pointless — the panel is
  // already hidden when you don't want it, so it always opens fully expanded
  // regardless of the persisted desktop preference.
  const collapsed = sidebarCollapsed && !isMobile;
  const resize = useSidebarResize(collapsed || isMobile);

  /** Dismiss the drawer on nav clicks that actually navigate in-place. */
  const closeDrawerOnNav = (event: React.MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    drawer?.close();
  };

  const renderedFooter =
    typeof footerSlot === "function" ? footerSlot(collapsed) : footerSlot;
  // The order the learner dragged the history region into — conversation ids
  // and group ids in one list, since the two are peers there. Like the
  // collapse preference above it is per-machine view state, hydrated after
  // mount.
  const [sessionOrder, setSessionOrder] = useState<string[]>([]);
  const sessionOrderRef = useRef<string[]>([]);

  useEffect(() => {
    const stored = readSessionOrder();
    sessionOrderRef.current = stored;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSessionOrder(stored);
  }, []);

  // A drag only ever speaks for the entries on screen, so it is merged into
  // the stored order rather than replacing it.
  const handleReorderSessions = useCallback((nextIds: string[]) => {
    const merged = mergeManualOrder(sessionOrderRef.current, nextIds);
    sessionOrderRef.current = merged;
    setSessionOrder(merged);
    writeSessionOrder(merged);
  }, []);

  const handleResetSessionOrder = useCallback(() => {
    sessionOrderRef.current = [];
    setSessionOrder([]);
    writeSessionOrder([]);
  }, []);

  const handleHomeClick = (event: React.MouseEvent) => {
    // Always reset to a fresh session (mirrors the old "New Chat" affordance);
    // let modifier-clicks fall through to default Link behavior so middle-click
    // open-in-new-tab still works.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    event.preventDefault();
    drawer?.close();
    onNewChat?.();
    navigateTask("/chat", router.push);
  };

  // Everything the learner has, minus the archived and minus the tutor threads
  // that render nested under the conversation that spawned them.
  //
  // Keep the complete index here. OrganizedSessionList limits the initial
  // rendering and exposes older conversations through Show more.
  const visibleSessions = sessions.filter(
    (session) =>
      !session.preferences?.archived && !session.preferences?.parent_session_id,
  );

  /* ---- Collapsed state ---- */
  if (collapsed) {
    return (
      <aside className="group/sb relative flex h-dvh w-[60px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 transition-all duration-200">
        {/* Header: logo + collapse toggle (toggle replaces logo on hover) */}
        <div className="relative mb-2 flex h-9 w-9 items-center justify-center">
          <Link
            href="/"
            prefetch={false}
            aria-label="DeepTutor"
            className="flex items-center justify-center transition-opacity duration-150 group-hover/sb:opacity-0"
          >
            <Image
              src="/logo.png"
              alt="DeepTutor"
              width={22}
              height={22}
              className="h-[22px] w-[22px] rounded-md"
            />
          </Link>
          <button
            onClick={() => setCollapsed(false)}
            className="absolute inset-0 flex items-center justify-center rounded-lg text-[var(--muted-foreground)] opacity-0 transition-all duration-150 hover:bg-background/60 hover:text-[var(--foreground)] group-hover/sb:opacity-100"
            aria-label={t("Expand sidebar")}
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>

        <SidebarHome collapsed onHomeClick={handleHomeClick} />
        <div className="min-h-0 w-full flex-1 overflow-y-auto overscroll-contain">
          <SidebarNav
            collapsed
            onHomeClick={handleHomeClick}
            onNavigate={closeDrawerOnNav}
          />
        </div>

        {/* Secondary nav + footer */}
        <div className="flex w-full shrink-0 flex-col items-center gap-1 px-1.5">
          <div className="my-1 h-px w-7 bg-border/40" />
          {SECONDARY_NAV.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                prefetch={false}
                title={t(item.label) as string}
                className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                  active
                    ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
                    : "text-foreground/85 hover:bg-background/60 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
              </Link>
            );
          })}
          {renderedFooter}
          <VersionBadge onNavigate={closeDrawerOnNav} />
        </div>
      </aside>
    );
  }

  /* ---- Expanded state ---- */
  return (
    <aside
      style={{ "--sidebar-width": `${resize.width}px` } as CSSProperties}
      className="relative flex h-dvh w-[var(--sidebar-width)] max-w-[45vw] shrink-0 flex-col bg-[var(--secondary)] max-md:w-[220px] max-md:max-w-[85vw]"
    >
      {/* Header: logo + collapse toggle */}
      <div className="flex h-[52px] shrink-0 items-center justify-between px-4">
        <Link href="/" prefetch={false} className="group flex items-center gap-1.5">
          <Image
            src="/logo.png"
            alt="DeepTutor"
            width={22}
            height={22}
            className="h-[22px] w-[22px] transition-transform duration-200 group-hover:scale-105"
          />
          <Image
            src="/banner.png"
            alt="DeepTutor"
            width={897}
            height={236}
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

      <SidebarHome onHomeClick={handleHomeClick} />

      {/* Modules and conversations share one scroll region below Home. */}
      <div
        ref={recentsScrollRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-2"
      >
        <SidebarNav
          scrollRef={recentsScrollRef}
          collapsed={false}
          onHomeClick={handleHomeClick}
          onNavigate={closeDrawerOnNav}
        />

        {/* Conversation history follows the module entries in the same scroller. */}
        {showSessions &&
        onSelectSession &&
        onRenameSession &&
        onDeleteSession ? (
          <section className="mt-3 px-2 pt-0.5">
            {!onOrganizeSession && <div className="mb-2 px-2 text-xs text-[var(--muted-foreground)]">{t("Recent")}</div>}
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
            ) : onOrganizeSession ? (
              <OrganizedSessionList
                sessions={visibleSessions}
                // Course grouping temporarily hidden pending further product
                // work; passing [] keeps the list flat without touching the
                // course data callers still fetch.
                courses={[]}
                workspaces={workspaces}
                groupWorkspaces
                onNewWorkspaceChat={onNewWorkspaceChat}
                masteryTopics={masteryTopics}
                readingCollections={readingCollections}
                activeSessionId={activeSessionId}
                liveSessionIds={liveSessionIds}
                manualOrder={sessionOrder}
                onReorder={handleReorderSessions}
                onResetOrder={handleResetSessionOrder}
                scrollRef={recentsScrollRef}
                onSelect={(sessionId) => {
                  drawer?.close();
                  return onSelectSession(sessionId);
                }}
                onRename={onRenameSession}
                onDelete={onDeleteSession}
                onOrganize={onOrganizeSession}
              />
            ) : (
              <SessionList
                sessions={visibleSessions}
                activeSessionId={activeSessionId}
                onSelect={(sessionId) => {
                  drawer?.close();
                  return onSelectSession(sessionId);
                }}
                onRename={onRenameSession}
                onDelete={onDeleteSession}
                compact
              />
            )}
          </section>
        ) : null}
      </div>

      {/* Secondary nav + footer */}
      <div className="shrink-0 border-t border-border/40 px-2 py-2">
        {renderedFooter}
        <div className="flex items-center gap-1">
          {SECONDARY_NAV.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                prefetch={false}
                onClick={closeDrawerOnNav}
                className={`flex min-h-8 min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                    : "text-foreground/85 hover:bg-background/60 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={15} strokeWidth={active ? 1.9 : 1.6} />
                <span>{t(item.label)}</span>
              </Link>
            );
          })}
          <VersionBadge onNavigate={closeDrawerOnNav} />
        </div>
      </div>
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
    </aside>
  );
}
