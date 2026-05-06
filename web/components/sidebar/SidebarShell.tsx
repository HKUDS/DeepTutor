"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode } from "react";
import { useAppShell } from "@/context/AppShellContext";
import {
  BookOpen,
  Bot,
  Github,
  LayoutGrid,
  Library,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plus,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import SessionList from "@/components/SessionList";
import { TutorBotRecent } from "@/components/sidebar/TutorBotRecent";
import { VersionBadge } from "@/components/sidebar/VersionBadge";
import type { SessionSummary } from "@/lib/session-api";
import clsx from "clsx";

interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
}

const PRIMARY_NAV: NavEntry[] = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/agents", label: "TutorBot", icon: Bot },
  { href: "/co-writer", label: "Co-Writer", icon: PenLine },
  { href: "/book", label: "Book", icon: Library },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/space", label: "Space", icon: LayoutGrid },
];

const SECONDARY_NAV: NavEntry[] = [
  { href: "/settings", label: "Settings", icon: Settings },
];
const DEFAULT_SESSION_VIEWPORT_CLASS_NAME = "max-h-[112px]";
const GITHUB_REPO_URL = "https://github.com/HKUDS/DeepTutor";

interface SidebarShellProps {
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
  loadingSessions?: boolean;
  showSessions?: boolean;
  sessionViewportClassName?: string;
  onNewChat?: () => void;
  onSelectSession?: (sessionId: string) => void | Promise<void>;
  onRenameSession?: (sessionId: string, title: string) => void | Promise<void>;
  onDeleteSession?: (sessionId: string) => void | Promise<void>;
  footerSlot?: ReactNode;
}

export function SidebarShell({
  sessions = [],
  activeSessionId = null,
  loadingSessions = false,
  showSessions = false,
  sessionViewportClassName = DEFAULT_SESSION_VIEWPORT_CLASS_NAME,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  footerSlot,
}: SidebarShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed } =
    useAppShell();

  // Detect if running in Electron desktop client
  const isDesktopClient = useMemo(
    () =>
      typeof navigator !== "undefined" &&
      navigator.userAgent.includes("Electron"),
    []
  );

  // Desktop-specific state
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const effectiveCollapsed = isDesktopClient ? desktopCollapsed : collapsed;
  const setEffectiveCollapsed = isDesktopClient ? setDesktopCollapsed : setCollapsed;

  const handleNewChat = () => {
    if (onNewChat) {
      onNewChat();
      return;
    }
    router.push("/chat");
  };

  /* ---- Collapsed state ---- */
  if (effectiveCollapsed) {
    const desktopTint = isDesktopClient ? "rgba(255, 255, 255, 0.08)" : undefined;
    return (
      <aside
        className={clsx(
          "group/sb relative flex h-full w-[60px] shrink-0 flex-col items-center py-3 transition-all duration-200",
          isDesktopClient ? "bg-transparent" : "bg-[var(--secondary)]"
        )}
        style={isDesktopClient ? { background: desktopTint, WebkitAppRegion: "drag" } as React.CSSProperties : undefined}
      >
        {/* Traffic light clearance for macOS desktop */}
        {isDesktopClient && (
          <div className="h-14 shrink-0" />
        )}

        {/* Header: logo + collapse toggle (toggle replaces logo on hover) */}
        <div className="relative mb-2 flex h-9 w-9 items-center justify-center" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          <Link
            href="/"
            aria-label="DeepTutor"
            className="flex items-center justify-center transition-opacity duration-150 group-hover/sb:opacity-0"
          >
            <Image
              src="/logo-ver2.png"
              alt="DeepTutor"
              width={22}
              height={22}
              className="h-[22px] w-[22px] rounded-md"
            />
          </Link>
          <button
            onClick={() => setEffectiveCollapsed(false)}
            className="absolute inset-0 flex items-center justify-center rounded-lg text-[var(--muted-foreground)] opacity-0 transition-all duration-150 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)] group-hover/sb:opacity-100"
            aria-label={t("Expand sidebar")}
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>

        {/* New chat — visually distinct circular button */}
        <button
          onClick={handleNewChat}
          title={t("New Chat") as string}
          className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--border)]/50 bg-[var(--background)]/40 text-[var(--foreground)] shadow-sm transition-all duration-150 hover:border-[var(--border)] hover:bg-[var(--background)]/80"
          aria-label={t("New Chat")}
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <Plus size={16} strokeWidth={2.2} />
        </button>

        {/* Subtle divider */}
        <div className="my-1.5 h-px w-7 bg-[var(--border)]/40" />

        {/* Primary nav */}
        <nav className="flex w-full flex-col items-center gap-1 px-1.5" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          {PRIMARY_NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={t(item.label) as string}
                className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                  active
                    ? "bg-[var(--background)]/80 text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
                }`}
              >
                {active && (
                  <span className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-[var(--foreground)]/80" />
                )}
                <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Secondary nav + footer */}
        <div className="flex w-full flex-col items-center gap-1 px-1.5" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
          <div className="my-1 h-px w-7 bg-[var(--border)]/40" />
          {SECONDARY_NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={t(item.label) as string}
                className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                  active
                    ? "bg-[var(--background)]/80 text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
                }`}
              >
                {active && (
                  <span className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-[var(--foreground)]/80" />
                )}
                <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
              </Link>
            );
          })}
          {footerSlot}
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            title="GitHub"
            aria-label="GitHub"
            className="mt-1 flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          >
            <Github size={15} strokeWidth={1.6} />
          </a>
          <VersionBadge collapsed />
        </div>
      </aside>
    );
  }

  /* ---- Expanded state ---- */
  const desktopTint = isDesktopClient ? "rgba(255, 255, 255, 0.08)" : undefined;
  return (
    <aside
      className={clsx(
        "flex h-full shrink-0 flex-col transition-all duration-200",
        isDesktopClient ? "w-0" : "w-[220px]",
        isDesktopClient ? "bg-transparent" : "bg-[var(--secondary)]"
      )}
      style={
        isDesktopClient
          ? ({
              width: 220,
              background: desktopTint,
              WebkitAppRegion: "drag" as const,
            } as React.CSSProperties)
          : undefined
      }
    >
      {/* Traffic light clearance for macOS desktop */}
      {isDesktopClient && <div className="h-14 shrink-0" />}

      {/* Header: logo + collapse toggle */}
      <div
        className="flex h-14 items-center justify-between px-4"
        style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
      >
        <Link href="/" className="group flex items-center gap-2">
          <Image
            src="/logo-ver2.png"
            alt="DeepTutor"
            width={22}
            height={22}
            className="h-[22px] w-[22px] transition-transform duration-200 group-hover:scale-105"
          />
          <span className="text-[16px] font-semibold leading-none tracking-[-0.02em] text-[var(--foreground)]">
            DeepTutor
          </span>
        </Link>
        <button
          onClick={() => setEffectiveCollapsed(true)}
          className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          aria-label={t("Collapse sidebar")}
        >
          <PanelLeftClose size={15} />
        </button>
      </div>

      {/* Primary nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-1" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        <div className="space-y-px">
          {/* New chat */}
          <button
            onClick={handleNewChat}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
          >
            <Plus size={16} strokeWidth={2} />
            <span>{t("New Chat")}</span>
          </button>

          {PRIMARY_NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            const hasSessionsBelow =
              item.href === "/chat" &&
              showSessions &&
              onSelectSession &&
              onRenameSession &&
              onDeleteSession;
            const hasBots = item.href === "/agents";
            return (
              <div key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                    active
                      ? "bg-[var(--background)]/70 font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
                  }`}
                >
                  <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
                  <span>{t(item.label)}</span>
                </Link>
                {hasSessionsBelow && (
                  <div
                    className={`${sessionViewportClassName} overflow-y-auto`}
                  >
                    <SessionList
                      sessions={sessions}
                      activeSessionId={activeSessionId}
                      loading={loadingSessions}
                      onSelect={onSelectSession}
                      onRename={onRenameSession}
                      onDelete={onDeleteSession}
                      compact
                    />
                  </div>
                )}
                {hasBots && <TutorBotRecent />}
              </div>
            );
          })}
        </div>
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Secondary nav + footer */}
      <div className="border-t border-[var(--border)]/40 px-2 py-2" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        {SECONDARY_NAV.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                active
                  ? "bg-[var(--background)]/70 font-medium text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
              }`}
            >
              <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
              <span>{t(item.label)}</span>
            </Link>
          );
        })}
        {footerSlot}
        <div className="mt-0.5 flex items-center gap-0.5">
          <VersionBadge />
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            title="GitHub"
            aria-label="GitHub"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
          >
            <Github size={13} strokeWidth={1.7} />
          </a>
        </div>
      </div>
    </aside>
  );
}
