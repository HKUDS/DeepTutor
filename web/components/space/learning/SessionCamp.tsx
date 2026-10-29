"use client";

import { masterySessionRoute, masterySessionsRoute } from "@/lib/learning-routes";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { ArrowRight, Loader2, MessageCircle, Plus, Radio } from "lucide-react";

import type { TopicSession } from "@/lib/learning-api";

import { formatRelative, type Translate } from "./format";

export function SessionCamp({
  pathId,
  sessions,
  loading,
  stale = false,
  onRetry,
  zh,
}: {
  pathId: string;
  sessions: TopicSession[];
  loading: boolean;
  /** The last fetch failed; whatever is listed may be out of date. */
  stale?: boolean;
  onRetry?: () => void;
  zh: boolean;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const openStudy = (sessionId?: string) =>
    router.push(
      sessionId
        ? masterySessionRoute(pathId, sessionId)
        : masterySessionsRoute(pathId),
    );

  return (
    // The one panel that grows without limit: a goal worked over months has
    // dozens of sessions. It takes whatever height is left in the column and
    // scrolls inside, so a long history can never push the rest of the
    // dashboard off screen.
    <aside className="dt-panel lg:flex-1">
      <div className="dt-panel-head">
        <div className="flex w-full items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <h2>{t("Mastery sessions")}</h2>
            {stale && (
              <button
                type="button"
                onClick={onRetry}
                className="text-[11px] text-[var(--muted-foreground)] underline underline-offset-2 transition hover:text-[var(--foreground)]"
              >
                {t("Could not refresh — retry")}
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => openStudy()}
            className="dt-quiet-button is-icon -mr-2 h-7 w-7"
            aria-label={t("Start a new learning session")}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="dt-panel-body flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex min-h-28 items-center justify-center text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <MessageCircle className="mx-auto h-7 w-7 text-[var(--muted-foreground)] opacity-45" />
            <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
              {t("No sessions yet")}
            </p>
            <p className="mx-auto mt-1 max-w-xs text-xs leading-5 text-[var(--muted-foreground)]">
              {t(
                "Start your first session. Later you can resume this thread or begin again from a fresh angle.",
              )}
            </p>
            <button
              type="button"
              onClick={() => openStudy()}
              className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-3.5 text-xs font-medium text-[var(--primary-foreground)]"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("Begin learning")}
            </button>
          </div>
        ) : (
          <div className="space-y-0.5">
            {sessions.map((session) => {
              const running =
                session.status === "running" || Boolean(session.active_turn_id);
              return (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => openStudy(session.session_id)}
                  className="dt-panel-row group"
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] ${
                      running
                        ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "bg-[var(--background)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    {running ? (
                      <Radio className="h-4 w-4 animate-pulse" />
                    ) : (
                      <MessageCircle className="h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-medium text-[var(--foreground)]">
                      {session.title || t("Untitled session")}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-[var(--muted-foreground)]">
                      {running
                        ? t("Tutor is responding")
                        : `${session.message_count} ${t("messages")} · ${formatRelative(session.updated_at, zh)}`}
                    </span>
                    {session.last_message && (
                      <span className="mt-1 block truncate text-[11px] text-[var(--muted-foreground)]/75">
                        {session.last_message}
                      </span>
                    )}
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)] opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => openStudy()}
              className="dt-panel-row mt-1 text-[12.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("Start from a fresh angle")}
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
