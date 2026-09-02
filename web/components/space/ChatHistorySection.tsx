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
import OrganizedSessionList from "@/components/courses/OrganizedSessionList";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { useAppShell } from "@/context/AppShellContext";
import {
  deleteSession,
  listAllSessions,
  updateSessionTitle,
  updateSessionOrganization,
  type SessionOrganizationPatch,
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
  const basePath = "/chat";
  const { t } = useTranslation();
  const router = useRouter();
  const { activeSessionId, setActiveSessionId } = useAppShell();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [courseFilter] = useState("all");
  const [kindFilter, setKindFilter] = useState("all");
  const [archiveFilter, setArchiveFilter] = useState("active");

  const load = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const nextSessions = await listAllSessions({ force });
      setSessions(nextSessions);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const filteredSessions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return sessions.filter((session) => {
      const prefs = session.preferences ?? {};
      if (archiveFilter === "active" && prefs.archived) return false;
      if (archiveFilter === "archived" && !prefs.archived) return false;
      if (courseFilter === "unclassified" && prefs.course_id) return false;
      if (
        courseFilter !== "all" &&
        courseFilter !== "unclassified" &&
        prefs.course_id !== courseFilter
      )
        return false;
      if (kindFilter === "chat" && prefs.session_kind === "selection_tutor")
        return false;
      if (
        kindFilter === "selection_tutor" &&
        prefs.session_kind !== "selection_tutor"
      )
        return false;
      if (!needle) return true;
      return [session.title, session.last_message]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle));
    });
  }, [archiveFilter, courseFilter, kindFilter, query, sessions]);

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

  const handleOrganize = useCallback(
    async (sessionId: string, patch: SessionOrganizationPatch) => {
      await updateSessionOrganization(sessionId, patch);
      await load(true);
    },
    [load],
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
          {/* Course filter temporarily hidden pending further product work;
              courseFilter stays at its "all" default so filteredSessions is
              unaffected. */}
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <label className="sr-only" htmlFor="history-kind-filter">
              {t("Filter by conversation type")}
            </label>
            <select
              id="history-kind-filter"
              value={kindFilter}
              onChange={(event) => setKindFilter(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            >
              <option value="all">{t("All conversation types")}</option>
              <option value="chat">{t("Main conversations")}</option>
              <option value="selection_tutor">{t("Tutor threads")}</option>
            </select>
            <label className="sr-only" htmlFor="history-archive-filter">
              {t("Filter by archive status")}
            </label>
            <select
              id="history-archive-filter"
              value={archiveFilter}
              onChange={(event) => setArchiveFilter(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            >
              <option value="active">{t("Active")}</option>
              <option value="archived">{t("Archived")}</option>
              <option value="all">{t("Active and archived")}</option>
            </select>
          </div>
        </div>

        <div className="px-3 py-3">
          {loading ? (
            <div className="space-y-2 p-2">
              {[0, 1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="h-8 animate-pulse rounded bg-[var(--muted)]/45"
                />
              ))}
            </div>
          ) : (
            <OrganizedSessionList
              sessions={filteredSessions}
              courses={[]}
              activeSessionId={activeSessionId}
              onSelect={handleSelect}
              onRename={handleRename}
              onDelete={handleDelete}
              onOrganize={handleOrganize}
            />
          )}
        </div>
      </section>
    </div>
  );
}
