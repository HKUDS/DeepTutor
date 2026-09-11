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
import ArchivedConversations from "@/components/space/ArchivedConversations";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { useAppShell } from "@/context/AppShellContext";
import {
  fetchMasteryTopicIndex,
  type MasteryTopicLabel,
} from "@/lib/learning-api";
import { sessionRoute } from "@/lib/mastery-session";
import {
  fetchReadingCollectionIndex,
  type ReadingCollectionLabel,
} from "@/lib/reading-workspace-api";
import { collectArchivedConversations } from "@/lib/session-archive";
import { notifySessionsChanged } from "@/lib/session-events";
import {
  deleteSession,
  listAllSessions,
  updateSessionTitle,
  updateSessionOrganization,
  type SessionOrganizationPatch,
  type SessionSummary,
} from "@/lib/session-api";

/**
 * The learning space's conversation history: search, filter, and the archive.
 *
 * A conversation reopens on the surface it was held in (see ``sessionRoute``),
 * not always in the main chat. This page used to send everything to `/chat`,
 * which for a reading conversation meant reopening it with its material closed
 * and its citations pointing at a document that is not on screen.
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
  const [masteryTopics, setMasteryTopics] = useState<MasteryTopicLabel[]>([]);
  const [readingCollections, setReadingCollections] = useState<
    ReadingCollectionLabel[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [courseFilter] = useState("all");
  const [kindFilter, setKindFilter] = useState("all");
  const [archiveFilter, setArchiveFilter] = useState("active");

  // ``quiet`` refetches without swapping the panel for its skeleton: a restore
  // acts on one row and says so on that row, so blanking the whole archive
  // underneath it would be the only thing the eye followed.
  const load = useCallback(async (force = false, quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      // Topic and collection labels only name which surface an archived
      // conversation came from, so losing them costs that line, never the
      // conversation.
      const [nextSessions, nextTopics, nextCollections] = await Promise.all([
        listAllSessions({ force }),
        fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
        fetchReadingCollectionIndex().catch(
          () => [] as ReadingCollectionLabel[],
        ),
      ]);
      setSessions(nextSessions);
      setMasteryTopics(nextTopics);
      setReadingCollections(nextCollections);
    } finally {
      if (!quiet) setLoading(false);
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
      const session = sessions.find((item) => item.session_id === sessionId);
      router.push(session ? sessionRoute(session) : `${basePath}/${sessionId}`);
    },
    [basePath, router, sessions, setActiveSessionId],
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

  // The archived view is built from the same filtered set as the list, so the
  // search box and the type filter still narrow it.
  const archiveBuckets = useMemo(
    () =>
      collectArchivedConversations({
        sessions: filteredSessions,
        masteryTopics,
        readingCollections,
      }),
    [filteredSessions, masteryTopics, readingCollections],
  );

  const handleRestore = useCallback(
    async (sessionId: string) => {
      setRestoringId(sessionId);
      try {
        await updateSessionOrganization(sessionId, { archived: false });
        // Restoring cascades to the tutor threads under the conversation, so
        // the server's own list is what says which rows are left.
        await load(true, true);
        notifySessionsChanged();
      } finally {
        setRestoringId(null);
      }
    },
    [load],
  );

  const handleOrganize = useCallback(
    async (sessionId: string, patch: SessionOrganizationPatch) => {
      await updateSessionOrganization(sessionId, patch);
      await load(true);
      // Archiving or restoring here changes what the sidebar beside this page
      // is allowed to show, and that list was fetched when the shell mounted.
      notifySessionsChanged();
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
          ) : archiveFilter === "archived" ? (
            <ArchivedConversations
              buckets={archiveBuckets}
              restoringId={restoringId}
              onOpen={handleSelect}
              onRestore={handleRestore}
            />
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
