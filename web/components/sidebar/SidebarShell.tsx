"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useAppShell } from "@/context/AppShellContext";
import { BookText, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { BrandGlyph } from "@/components/common/BrandIcon";
import OrganizedSessionList from "@/components/courses/OrganizedSessionList";
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
import { masteryPathIdOf, readingWorkspaceIdOf } from "@/lib/mastery-session";
import type { StudyCourse } from "@/lib/courses-api";
import { SidebarNav } from "@/components/sidebar/SidebarNav";
import { SECONDARY_NAV, isNavActive } from "@/components/sidebar/nav-entries";
import {
  mergeManualOrder,
  readSessionOrder,
  writeSessionOrder,
} from "@/lib/sidebar-layout";

const GITHUB_REPO_URL = "https://github.com/HKUDS/DeepTutor";
const DOCS_URL = "https://deeptutor.info/";

interface SidebarShellProps {
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
  loadingSessions?: boolean;
  showSessions?: boolean;
  /** Clicking the Chat nav item resets to a fresh session via this handler. */
  onNewChat?: () => void;
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
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const { sidebarCollapsed, setSidebarCollapsed: setCollapsed } = useAppShell();
  const { isMobile } = useDevice();
  const drawer = useSidebarDrawer();
  const recentsScrollRef = useRef<HTMLDivElement>(null);

  // Inside the mobile drawer the icon-only rail is pointless — the panel is
  // already hidden when you don't want it, so it always opens fully expanded
  // regardless of the persisted desktop preference.
  const collapsed = sidebarCollapsed && !isMobile;

  /** Dismiss the drawer on nav clicks that actually navigate in-place. */
  const closeDrawerOnNav = (event: React.MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1)
      return;
    drawer?.close();
  };

  const renderedFooter =
    typeof footerSlot === "function" ? footerSlot(collapsed) : footerSlot;
  // The order the learner dragged the chat history into. Like the collapse
  // preference above it is a per-machine view state, hydrated after mount.
  const [sessionOrder, setSessionOrder] = useState<string[]>([]);
  const sessionOrderRef = useRef<string[]>([]);

  useEffect(() => {
    const stored = readSessionOrder();
    sessionOrderRef.current = stored;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSessionOrder(stored);
  }, []);

  // A drag only ever speaks for the rows on screen, so it is merged into the
  // stored order rather than replacing it.
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
    router.push("/chat");
  };

  // The Chat group shows the last 8 home conversations. Grouped ones are
  // exempt from that cut: a topic heading that says "4" while listing two of
  // them is worse than a slightly longer list, and the groups collapse anyway.
  const visibleSessions = sessions.filter(
    (session) =>
      !session.preferences?.archived && !session.preferences?.parent_session_id,
  );
  // Which conversations make the window is recency's call; the hand-arranged
  // order (applied inside the list) decides how the ones that made it are
  // stacked. Ordering before the cut instead would let an old arrangement keep
  // newer chats out of the sidebar entirely.
  // Grouped conversations are exempt from the cut — a heading that says "4"
  // while listing two of them is worse than a slightly longer list, and the
  // groups collapse anyway. Reading conversations group the same way study
  // ones do, so they are exempt on the same terms.
  const isGrouped = (session: SessionSummary) =>
    Boolean(masteryPathIdOf(session)) || Boolean(readingWorkspaceIdOf(session));
  const recentSessions = [
    ...visibleSessions.filter((session) => !isGrouped(session)).slice(0, 8),
    ...visibleSessions.filter(isGrouped),
  ];

  /* ---- Collapsed state ---- */
  if (collapsed) {
    return (
      <aside className="group/sb relative flex h-dvh w-[60px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 transition-all duration-200">
        {/* Header: logo + collapse toggle (toggle replaces logo on hover) */}
        <div className="relative mb-2 flex h-9 w-9 items-center justify-center">
          <Link
            href="/"
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
            className="absolute inset-0 flex items-center justify-center rounded-lg text-[var(--muted-foreground)] opacity-0 transition-all duration-150 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)] group-hover/sb:opacity-100"
            aria-label={t("Expand sidebar")}
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>

        {/* Primary nav — order and folding are the learner's, see SidebarNav */}
        <SidebarNav
          collapsed
          onHomeClick={handleHomeClick}
          onNavigate={closeDrawerOnNav}
        />

        <div className="flex-1" />

        {/* Secondary nav + footer */}
        <div className="flex w-full flex-col items-center gap-1 px-1.5">
          <div className="my-1 h-px w-7 bg-[var(--border)]/40" />
          {SECONDARY_NAV.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={t(item.label) as string}
                className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                  active
                    ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
              </Link>
            );
          })}
          {renderedFooter}
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noreferrer noopener"
            title={t("Docs") as string}
            aria-label={t("Docs") as string}
            className="mt-1 flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          >
            <BookText
              size={15}
              strokeWidth={1.8}
              className="text-blue-600 dark:text-blue-400"
            />
          </a>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            title="GitHub"
            aria-label="GitHub"
            className="flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          >
            <BrandGlyph
              namespace="mcp"
              id="github"
              size={15}
              className="text-[#181717] dark:text-white"
            />
          </a>
          <VersionBadge collapsed />
        </div>
      </aside>
    );
  }

  /* ---- Expanded state ---- */
  return (
    <aside className="flex w-[220px] h-dvh shrink-0 flex-col bg-[var(--secondary)] transition-all duration-200">
      {/* Header: logo + collapse toggle */}
      <div className="flex h-14 items-center justify-between px-4">
        <Link href="/" className="group flex items-center gap-1.5">
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

      {/* Primary nav */}
      <SidebarNav
        collapsed={false}
        onHomeClick={handleHomeClick}
        onNavigate={closeDrawerOnNav}
      />

      {/* Chat history — its own region below the nav, takes remaining height */}
      {showSessions && onSelectSession && onRenameSession && onDeleteSession ? (
        <section className="mt-3 flex min-h-0 flex-1 flex-col">
          <div
            ref={recentsScrollRef}
            className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 pt-0.5"
          >
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
                sessions={recentSessions}
                // Course grouping temporarily hidden pending further product
                // work; passing [] keeps the list flat without touching the
                // course data callers still fetch.
                courses={[]}
                masteryTopics={masteryTopics}
                readingCollections={readingCollections}
                activeSessionId={activeSessionId}
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
                sessions={recentSessions}
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
          </div>
        </section>
      ) : null}

      {/* With no session list at all, fill the gap above the footer. */}
      {(!showSessions ||
        !onSelectSession ||
        !onRenameSession ||
        !onDeleteSession) && <div className="flex-1" />}

      {/* Secondary nav + footer */}
      <div className="border-t border-[var(--border)]/40 px-2 py-2">
        {SECONDARY_NAV.map((item) => {
          const active = isNavActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={closeDrawerOnNav}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                active
                  ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                  : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
              }`}
            >
              <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
              <span>{t(item.label)}</span>
            </Link>
          );
        })}
        {renderedFooter}
        <div className="mt-0.5 flex items-center gap-0.5">
          <VersionBadge />
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noreferrer noopener"
            title={t("Docs") as string}
            aria-label={t("Docs") as string}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
          >
            <BookText
              size={15}
              strokeWidth={1.9}
              className="text-blue-600 dark:text-blue-400"
            />
          </a>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            title="GitHub"
            aria-label="GitHub"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
          >
            <BrandGlyph
              namespace="mcp"
              id="github"
              size={15}
              className="text-[#181717] dark:text-white"
            />
          </a>
        </div>
      </div>
    </aside>
  );
}
