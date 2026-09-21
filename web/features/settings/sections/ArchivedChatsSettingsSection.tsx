"use client";

import { navigateTask } from "@/lib/workspace-scope";
import { sessionWorkspaceId } from "@/lib/session-api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, RefreshCw, Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SettingsPageHeader } from "@/components/settings/shared";
import ArchivedConversations from "@/components/space/ArchivedConversations";
import { useAppShell } from "@/context/AppShellContext";
import {
  fetchMasteryTopicIndex,
  type MasteryTopicLabel,
} from "@/lib/learning-api";
import {
  fetchReadingCollectionIndex,
  type ReadingCollectionLabel,
} from "@/lib/reading-workspace-api";
import {
  deleteSession,
  listAllSessions,
  updateSessionOrganization,
  type SessionSummary,
} from "@/lib/session-api";
import {
  archiveCount,
  collectArchivedConversations,
  type ArchiveBuckets,
  type ArchiveKind,
} from "@/lib/session-archive";
import { notifySessionsChanged } from "@/lib/session-events";
import { sessionRoute } from "@/lib/mastery-session";

export default function ArchivedChatsSettingsSection() {
  const { t } = useTranslation();
  const router = useRouter();
  const { activeSessionId, setActiveSessionId } = useAppShell();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [topics, setTopics] = useState<MasteryTopicLabel[]>([]);
  const [collections, setCollections] = useState<ReadingCollectionLabel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<ArchiveKind | "all">("all");

  const load = useCallback(async () => {
    const [nextSessions, nextTopics, nextCollections] = await Promise.all([
      listAllSessions({ force: true, allWorkspaces: true }),
      fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
      fetchReadingCollectionIndex().catch(() => [] as ReadingCollectionLabel[]),
    ]);
    setSessions(nextSessions);
    setTopics(nextTopics);
    setCollections(nextCollections);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await load();
    } catch {
      setError(t("Unable to load archived chats. Please try again."));
    } finally {
      setLoading(false);
    }
  }, [load, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const buckets = useMemo(
    () =>
      collectArchivedConversations({
        sessions,
        masteryTopics: topics,
        readingCollections: collections,
      }),
    [sessions, topics, collections],
  );
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const result: ArchiveBuckets = { chat: [], mastery: [], reading: [] };
    for (const key of ["chat", "mastery", "reading"] as const) {
      if (kind !== "all" && kind !== key) continue;
      result[key] = buckets[key].filter(({ session, container }) =>
        [session.title, session.last_message, container]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
          .includes(needle),
      );
    }
    return result;
  }, [buckets, query, kind]);
  const count = archiveCount(buckets);

  const mutate = async (id: string, operation: () => Promise<void>) => {
    if (busy) return;
    setBusy(id);
    setError("");
    try {
      await operation();
      await load();
    } catch {
      setError(
        t("Some changes could not be completed. Please refresh and try again."),
      );
      await load().catch(() => {});
    } finally {
      notifySessionsChanged();
      setBusy(null);
    }
  };

  const remove = async (sessionId: string) => {
    await deleteSession(sessionId, sessionWorkspaceId(sessions.find(item => item.session_id === sessionId)));
    if (activeSessionId === sessionId) setActiveSessionId(null);
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-4">
        <SettingsPageHeader title={t("Archived chats")} />
        <button
          type="button"
          disabled={loading || !!busy || !count}
          onClick={() => {
            if (
              !window.confirm(
                t(
                  "Permanently delete all {{count}} archived chats and their tutor threads? This cannot be undone.",
                  { count },
                ),
              )
            )
              return;
            const ids = Object.values(buckets)
              .flat()
              .map(({ session }) => session.session_id);
            void mutate("all", async () => {
              let failed = false;
              for (let start = 0; start < ids.length; start += 4) {
                const results = await Promise.allSettled(
                  ids.slice(start, start + 4).map(remove),
                );
                failed ||= results.some(
                  (result) => result.status === "rejected",
                );
              }
              if (failed) throw new Error("Partial deletion");
            });
          }}
          className="mb-6 inline-flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-[13px] font-medium text-red-600 hover:bg-red-500/15 disabled:opacity-40 dark:text-red-400"
        >
          {busy === "all" ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <Trash2 size={15} />
          )}
          {t("Delete all archived chats")}
        </button>
      </div>
      <div className="mb-6 flex flex-wrap gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2">
          <Search
            size={16}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("Search archived chats")}
            placeholder={t("Search archived chats")}
            className="min-w-0 w-full bg-transparent text-[13px] outline-none"
          />
        </label>
        <select
          value={kind}
          onChange={(event) =>
            setKind(event.target.value as ArchiveKind | "all")
          }
          aria-label={t("Filter by conversation type")}
          className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px]"
        >
          <option value="all">{t("All conversation types")}</option>
          <option value="chat">{t("Conversations")}</option>
          <option value="mastery">{t("Mastery Path")}</option>
          <option value="reading">{t("Immersive Reading")}</option>
        </select>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || !!busy}
          aria-label={t("Refresh")}
          title={t("Refresh")}
          className="rounded-xl border border-[var(--border)] p-2.5 disabled:opacity-40"
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {error && (
        <p role="alert" className="mb-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {loading ? (
        <div
          role="status"
          className="flex items-center gap-2 py-8 text-sm text-[var(--muted-foreground)]"
        >
          <Loader2 size={16} className="animate-spin" />
          {t("Loading...")}
        </div>
      ) : count > 0 && archiveCount(visible) === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">
          {t("No archived chats match your search.")}
        </p>
      ) : !error || count > 0 ? (
        <ArchivedConversations
          buckets={visible}
          disabled={!!busy}
          restoringId={busy?.startsWith("restore:") ? busy.slice(8) : null}
          deletingId={busy?.startsWith("delete:") ? busy.slice(7) : null}
          onOpen={(id) => {
            const session = sessions.find((row) => row.session_id === id);
            if (session) {
              setActiveSessionId(id);
              navigateTask(sessionRoute(session), router.push);
            }
          }}
          onRestore={(id) =>
            void mutate(`restore:${id}`, async () => {
              await updateSessionOrganization(id, { archived: false }, sessionWorkspaceId(sessions.find(item => item.session_id === id)));
            })
          }
          onDelete={(id) => {
            if (
              !window.confirm(
                t(
                  "Permanently delete this chat and its tutor threads? This cannot be undone.",
                ),
              )
            )
              return;
            void mutate(`delete:${id}`, () => remove(id));
          }}
        />
      ) : null}
    </div>
  );
}
