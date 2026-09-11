"use client";

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
} from "react";
import { useAppShell } from "@/context/AppShellContext";
import { BookText, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
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
import { SidebarNav } from "@/components/sidebar/SidebarNav";
import { SECONDARY_NAV, isNavActive } from "@/components/sidebar/nav-entries";
import {
  mergeManualOrder,
  readSessionOrder,
  writeSessionOrder,
} from "@/lib/sidebar-layout";

const GITHUB_REPO_URL = "https://github.com/HKUDS/DeepTutor";
const DOCS_URL = "https://deeptutor.info/";

// The GitHub octocat mark (CC0 path from `simple-icons`, identical to the
// `github` entry in `lib/brand-icons.generated.ts`). Kept inline instead of
// going through <BrandGlyph/> so the whole generated brand-icon table — every
// store logo, ~95KB — does not ride along in the app-shell chunk that every
// route shares, for the sake of one footer link. Store surfaces that actually
// render brand rows still import the table through BrandIcon directly.
const GITHUB_MARK_PATH =
  "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12";

function GitHubMarkLink({
  className = "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]",
  size = 15,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <a
      href={GITHUB_REPO_URL}
      target="_blank"
      rel="noreferrer noopener"
      title="GitHub"
      aria-label="GitHub"
      className={className}
    >
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="currentColor"
        role="presentation"
        aria-hidden
        className="text-[#181717] dark:text-white"
      >
        <path d={GITHUB_MARK_PATH} />
      </svg>
    </a>
  );
}

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
            className="h-4 w-3/4 animate-pulse rounded bg-[var(--muted)]/40"
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
    router.push("/chat");
  };

  // Everything the learner has, minus the archived and minus the tutor threads
  // that render nested under the conversation that spawned them.
  //
  // No recents window any more. The region used to cut the home conversations
  // at eight, which was survivable only because the "Chat" heading above them
  // printed the real count; with the conversations listed directly there is
  // nothing on screen to say that older ones exist, and a sidebar that quietly
  // drops your conversation from yesterday is worse than one you scroll.
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
          <GitHubMarkLink className="flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]" />
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
                sessions={visibleSessions}
                // Course grouping temporarily hidden pending further product
                // work; passing [] keeps the list flat without touching the
                // course data callers still fetch.
                courses={[]}
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
          <GitHubMarkLink />
        </div>
      </div>
    </aside>
  );
}
