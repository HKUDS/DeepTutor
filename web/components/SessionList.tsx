"use client";

import { Check, Pencil, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { type SessionSummary } from "@/lib/session-api";
import { normalizeMessageContent, truncateText } from "@/lib/message-content";
import { SessionAvatar } from "@/components/sidebar/SessionAvatar";
import {
  formatRelativeTime,
  getDayGroupKey,
  type DayGroupKey,
} from "@/lib/relative-time";

type SessionRuntimeStatus =
  | "idle"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "rejected";

interface SessionListProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  loading?: boolean;
  compact?: boolean;
  onSelect: (sessionId: string) => void | Promise<void>;
  onRename: (sessionId: string, title: string) => void | Promise<void>;
  onDelete: (sessionId: string) => void | Promise<void>;
}

function StatusIndicator({ status }: { status?: SessionRuntimeStatus }) {
  if (!status || status === "idle") return null;

  if (status === "running") {
    return (
      <span className="relative ml-1.5 inline-flex shrink-0">
        <span className="session-pulse absolute inline-flex h-2 w-2 rounded-full bg-blue-400/60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
      </span>
    );
  }

  if (status === "completed") {
    return (
      <span className="ml-1.5 inline-flex h-2 w-2 shrink-0 rounded-full bg-emerald-400/50 ring-1 ring-emerald-400/10" />
    );
  }

  if (status === "failed") {
    return (
      <span className="ml-1.5 inline-flex h-2 w-2 shrink-0 rounded-full bg-rose-500/80 ring-1 ring-rose-500/20" />
    );
  }

  if (status === "rejected") {
    return (
      <span className="ml-1.5 inline-flex h-2 w-2 shrink-0 rounded-full bg-fuchsia-500/80 ring-1 ring-fuchsia-500/20" />
    );
  }

  if (status === "cancelled") {
    return (
      <span className="ml-1.5 inline-flex h-2 w-2 shrink-0 rounded-full bg-amber-500/70 ring-1 ring-amber-500/20" />
    );
  }

  return null;
}

export default function SessionList({
  sessions,
  activeSessionId,
  loading = false,
  compact = false,
  onSelect,
  onRename,
  onDelete,
}: SessionListProps) {
  const { t, i18n } = useTranslation();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  // The sentinel the backend writes when a session is created and not
  // yet renamed by the LLM title generator. We swap it for a localized
  // "New chat" string with a breathing animation so the sidebar shows
  // something "alive" while the title is being generated in the
  // background instead of a literal English sentinel.
  const isPlaceholderTitle = (raw: string | null | undefined): boolean => {
    const value = (raw ?? "").trim();
    return value === "" || value === "New conversation";
  };
  const placeholderLabel = t("New chat");

  // The group-key tokens stay stable; only the translated labels change.
  const groupLabels = useMemo<Record<DayGroupKey, string>>(
    () => ({
      today: t("Today"),
      yesterday: t("Yesterday"),
      last_7_days: t("Last 7 days"),
      earlier: t("Earlier"),
    }),
    [t],
  );

  const grouped = useMemo(() => {
    const buckets = new Map<DayGroupKey, SessionSummary[]>();
    for (const session of sessions) {
      const key = getDayGroupKey(session.updated_at);
      const current = buckets.get(key) ?? [];
      current.push(session);
      buckets.set(key, current);
    }
    return Array.from(buckets.entries());
  }, [sessions]);

  const startEdit = (session: SessionSummary) => {
    setEditingId(session.session_id);
    setDraftTitle(session.title);
  };

  const commitEdit = async () => {
    if (!editingId) return;
    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      setEditingId(null);
      setDraftTitle("");
      return;
    }
    await onRename(editingId, nextTitle);
    setEditingId(null);
    setDraftTitle("");
  };

  if (loading) {
    if (compact) {
      return (
        <div className="space-y-1.5 px-2 py-1">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-4 w-3/4 animate-pulse rounded bg-[var(--muted)]/40"
            />
          ))}
        </div>
      );
    }
    return (
      <div className="space-y-2 px-1.5 py-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-10 animate-pulse rounded-md bg-[var(--muted)]/60"
          />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    if (compact) {
      return (
        <div className="px-3 py-4 text-center text-[11px] text-[var(--muted-foreground)]/70">
          {t("No conversations yet")}
        </div>
      );
    }
    return (
      <div className="px-3 py-4 text-center text-[11px] text-[var(--muted-foreground)]/70">
        {t("No conversations yet")}
      </div>
    );
  }

  /* ---- Compact sidebar style (standalone chat history region) ---- */
  if (compact) {
    return (
      <div className="py-0.5">
        {sessions.map((session) => {
          const active = activeSessionId === session.session_id;
          const isEditing = editingId === session.session_id;
          return (
            <div
              key={session.session_id}
              onClick={() => void onSelect(session.session_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  void onSelect(session.session_id);
                }
              }}
              role="button"
              tabIndex={0}
              className={`group flex items-center gap-2 rounded-lg px-2.5 py-1.5 transition-colors ${
                active
                  ? "bg-[var(--background)]/50 text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
              }`}
            >
              <SessionAvatar
                sessionId={session.session_id}
                running={session.status === "running"}
                className={
                  session.status === "running" ? "text-blue-500" : "opacity-70"
                }
              />
              {isEditing ? (
                <input
                  value={draftTitle}
                  autoFocus
                  onChange={(event) => setDraftTitle(event.target.value)}
                  onBlur={() => void commitEdit()}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void commitEdit();
                    if (event.key === "Escape") {
                      setEditingId(null);
                      setDraftTitle("");
                    }
                  }}
                  onClick={(event) => event.stopPropagation()}
                  className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-px text-[12px] text-[var(--foreground)] outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                />
              ) : isPlaceholderTitle(session.title) ? (
                <span
                  className={`dt-breathing-text min-w-0 flex-1 truncate text-[13px] italic text-[var(--muted-foreground)] ${active ? "font-medium" : ""}`}
                >
                  {placeholderLabel}
                </span>
              ) : (
                <span
                  className={`min-w-0 flex-1 truncate text-[13px] ${active ? "font-medium" : ""}`}
                >
                  {session.title}
                </span>
              )}
              <div className="flex shrink-0 items-center gap-px opacity-0 transition-opacity group-hover:opacity-100">
                {isEditing ? (
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      void commitEdit();
                    }}
                    className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    aria-label={t("Save title")}
                  >
                    <Check size={10} />
                  </button>
                ) : (
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      startEdit(session);
                    }}
                    className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    aria-label={t("Rename chat")}
                  >
                    <Pencil size={10} />
                  </button>
                )}
                <button
                  onClick={(event) => {
                    event.stopPropagation();
                    void onDelete(session.session_id);
                  }}
                  className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--destructive)]"
                  aria-label={t("Delete chat")}
                >
                  <Trash2 size={10} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  /* ---- Classic style ---- */
  return (
    <div className="space-y-4">
      {grouped.map(([key, items]) => (
        <div key={key}>
          <div className="mb-1.5 px-2 text-[11px] font-semibold uppercase tracking-widest text-[var(--muted-foreground)]">
            {groupLabels[key]}
          </div>
          <div className="divide-y divide-[var(--border)]/45 overflow-hidden rounded-lg border border-[var(--border)]/45 bg-[var(--card)]/50">
            {items.map((session) => {
              const active = activeSessionId === session.session_id;
              const isEditing = editingId === session.session_id;
              return (
                <div
                  key={session.session_id}
                  onClick={() => void onSelect(session.session_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void onSelect(session.session_id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  className={`group relative w-full px-3 py-2.5 text-left transition-colors duration-150 ${
                    active
                      ? "bg-[var(--background)]/70 text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
                  }`}
                >
                  {active && (
                    <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--primary)]" />
                  )}
                  <div className="flex items-start gap-1.5">
                    <div className="min-w-0 flex-1">
                      {isEditing ? (
                        <input
                          value={draftTitle}
                          autoFocus
                          onChange={(event) =>
                            setDraftTitle(event.target.value)
                          }
                          onBlur={() => void commitEdit()}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") void commitEdit();
                            if (event.key === "Escape") {
                              setEditingId(null);
                              setDraftTitle("");
                            }
                          }}
                          onClick={(event) => event.stopPropagation()}
                          className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[12px] text-[var(--foreground)] outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                        />
                      ) : (
                        <div className="flex items-center">
                          {isPlaceholderTitle(session.title) ? (
                            <span
                              className={`dt-breathing-text line-clamp-1 min-w-0 flex-1 text-[12px] italic leading-snug text-[var(--muted-foreground)] ${
                                active ? "font-medium" : "font-normal"
                              }`}
                            >
                              {placeholderLabel}
                            </span>
                          ) : (
                            <span
                              className={`line-clamp-1 min-w-0 flex-1 text-[12px] leading-snug ${
                                active ? "font-medium" : "font-normal"
                              }`}
                            >
                              {session.title}
                            </span>
                          )}
                          <StatusIndicator status={session.status} />
                        </div>
                      )}
                      {!isEditing && (
                        <div className="mt-0.5 line-clamp-1 text-[11px] leading-tight text-[var(--muted-foreground)]">
                          {truncateText(
                            normalizeMessageContent(session.last_message),
                            120,
                          ) ||
                            formatRelativeTime(
                              session.updated_at,
                              i18n.language,
                            )}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5 pt-px opacity-0 transition-opacity group-hover:opacity-100">
                      {isEditing ? (
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            void commitEdit();
                          }}
                          className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                          aria-label={t("Save title")}
                        >
                          <Check size={12} />
                        </button>
                      ) : (
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            startEdit(session);
                          }}
                          className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                          aria-label={t("Rename chat")}
                        >
                          <Pencil size={11} />
                        </button>
                      )}
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void onDelete(session.session_id);
                        }}
                        className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--destructive)]"
                        aria-label={t("Delete chat")}
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
