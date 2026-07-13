"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  History,
  Loader2,
  RefreshCw,
  Search,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import SessionList from "@/components/SessionList";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { useAppShell } from "@/context/AppShellContext";
import {
  deleteSession,
  listSessions,
  updateSessionTitle,
  type SessionSummary,
} from "@/lib/session-api";

/**
 * Sessions list for chat history. Reopened sessions always route back to
 * the main chat surface.
 */
export interface ChatHistorySectionProps {
  icon?: LucideIcon;
  title?: string;
  description?: string;
}

export default function ChatHistorySection({
  icon,
  title,
  description,
}: ChatHistorySectionProps = {}) {
  const basePath = "/home";
  const { t } = useTranslation();
  const router = useRouter();
  const { activeSessionId, setActiveSessionId } = useAppShell();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const load = useCallback(async (force = false) => {
    setLoading(true);
    try {
      setSessions(await listSessions(200, 0, { force }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const filteredSessions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) =>
      [session.title, session.last_message]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [query, sessions]);

  const handleSelect = useCallback(
    (sessionId: string) => {
      setActiveSessionId(sessionId);
      router.push(`${basePath}/${sessionId}`);
    },
    [basePath, router, setActiveSessionId],
  );

  const handleRename = useCallback(
    async (sessionId: string, title: string) => {
      await updateSessionTitle(sessionId, title);
      await load(true);
    },
    [load],
  );

  const handleDelete = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this chat?"))) return;
      await deleteSession(sessionId);
      if (activeSessionId === sessionId) setActiveSessionId(null);
      setSessions((prev) =>
        prev.filter((session) => session.session_id !== sessionId),
      );
    },
    [activeSessionId, setActiveSessionId, t],
  );

  const HeaderIcon = icon ?? History;
  const headerTitle = title ?? t("Chat History");
  const headerDescription =
    description ??
    t(
      "Browse, rename, delete, and reopen previous conversations from your learning space.",
    );

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={HeaderIcon}
        title={headerTitle}
        description={headerDescription}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {sessions.length} {t("conversations")}
          </span>
        }
        action={
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {loading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {t("Refresh")}
          </button>
        }
      />

      <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
        <div className="border-b border-[var(--border)]/60 px-4 py-3">
          <label className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--muted-foreground)] focus-within:border-[var(--ring)]">
            <Search size={14} strokeWidth={1.7} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("Search chat history...")}
              className="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/55"
            />
          </label>
        </div>

        <div className="px-3 py-3">
          <SessionList
            sessions={filteredSessions}
            activeSessionId={activeSessionId}
            loading={loading}
            onSelect={handleSelect}
            onRename={handleRename}
            onDelete={handleDelete}
          />
        </div>
      </section>
    </div>
  );
}
