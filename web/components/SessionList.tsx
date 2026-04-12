"use client";

import { Check, Pencil, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { type SessionSummary } from "@/lib/session-api";

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

function statusColor(status?: SessionRuntimeStatus): string {
  switch (status) {
    case "running":
      return "bg-blue-500";
    case "completed":
      return "bg-emerald-400";
    case "failed":
      return "bg-rose-500";
    case "rejected":
      return "bg-fuchsia-500";
    case "cancelled":
      return "bg-amber-500";
    default:
      return "bg-[var(--muted-foreground)]/25";
  }
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

function groupLabel(timestamp: number): string {
  const now = new Date();
  const date = new Date(timestamp * 1000);
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfItemDay = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.floor((startOfToday - startOfItemDay) / 86400000);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "Last 7 days";
  return "Earlier";
}

function relativeTime(timestamp: number): string {
  const diffSeconds = Math.round(timestamp - Date.now() / 1000);
  const formatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  const abs = Math.abs(diffSeconds);
  if (abs < 60) return formatter.format(diffSeconds, "second");
  if (abs < 3600) return formatter.format(Math.round(diffSeconds / 60), "minute");
  if (abs < 86400) return formatter.format(Math.round(diffSeconds / 3600), "hour");
  return formatter.format(Math.round(diffSeconds / 86400), "day");
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const grouped = useMemo(() => {
    const buckets = new Map<string, SessionSummary[]>();
    for (const session of sessions) {
      const label = groupLabel(session.updated_at);
      const current = buckets.get(label) ?? [];
      current.push(session);
      buckets.set(label, current);
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
        <div className="ml-5 space-y-1.5 border-l border-[var(--border)]/30 py-1 pl-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-4 w-3/4 animate-pulse rounded bg-[var(--muted)]/40" />
          ))}
        </div>
      );
    }
    return (
      <div className="space-y-2 px-1.5 py-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded-md bg-[var(--muted)]/60" />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    if (compact) return null;
    return (
      <div className="px-3 py-4 text-center text-[11px] text-[var(--muted-foreground)]/70">
        No sessions yet
      </div>
    );
  }

  /* ---- Compact tree-line style (under Chat nav item) ---- */
  if (compact) {
    return (
      <div className="ml-5 border-l border-[var(--border)]/30 py-1">
        {grouped.map(([label, items], groupIdx) => (
          <div key={label}>
            {groupIdx > 0 && (
              <div className="my-1 ml-3 mr-2 border-t border-[var(--border)]/20" />
            )}
            <div className="px-3 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]/40">
              {label}
            </div>
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
                  className={`group flex items-center gap-2 rounded-r-lg py-1 pl-3 pr-2 transition-colors ${
                    active
                      ? "bg-[var(--background)]/50 text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
                  }`}
                >
                  <span className={`block h-1.5 w-1.5 shrink-0 rounded-full ${
                    active ? "bg-[var(--foreground)]/60" : statusColor(session.status)
                  }`} />
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
                  ) : (
                    <span className={`min-w-0 flex-1 truncate text-[13px] ${active ? "font-medium" : ""}`}>
                      {session.title || "Untitled session"}
                    </span>
                  )}
                  <div className="flex shrink-0 items-center gap-px opacity-0 transition-opacity group-hover:opacity-100">
                    {isEditing ? (
                      <button
                        onClick={(event) => { event.stopPropagation(); void commitEdit(); }}
                        className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        aria-label="Save title"
                      >
                        <Check size={10} />
                      </button>
                    ) : (
                      <button
                        onClick={(event) => { event.stopPropagation(); startEdit(session); }}
                        className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        aria-label="Rename session"
                      >
                        <Pencil size={10} />
                      </button>
                    )}
                    <button
                      onClick={(event) => { event.stopPropagation(); void onDelete(session.session_id); }}
                      className="rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--destructive)]"
                      aria-label="Delete session"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    );
  }

  /* ---- Classic style ---- */
  return (
    <div className="space-y-3">
      {grouped.map(([label, items]) => (
        <div key={label}>
          <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-widest text-[var(--muted-foreground)]">
            {label}
          </div>
          <div className="space-y-px">
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
                  className={`group relative w-full rounded-lg px-2.5 py-2 text-left transition-all duration-150 ${
                    active
                      ? "bg-[var(--background)]/70 text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
                  }`}
                >
                  {active && (
                    <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--primary)]" />
                  )}
                  <div className="flex items-start gap-1.5">
                    <div className="min-w-0 flex-1">
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
                          className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[12px] text-[var(--foreground)] outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                        />
                      ) : (
                        <div className="flex items-center">
                          <span
                            className={`line-clamp-1 min-w-0 flex-1 text-[12px] leading-snug ${
                              active ? "font-medium" : "font-normal"
                            }`}
                          >
                            {session.title || "Untitled session"}
                          </span>
                          <StatusIndicator status={session.status} />
                        </div>
                      )}
                      {!isEditing && (
                        <div className="mt-0.5 line-clamp-1 text-[11px] leading-tight text-[var(--muted-foreground)]">
                          {session.last_message || relativeTime(session.updated_at)}
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
                          aria-label="Save title"
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
                          aria-label="Rename session"
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
                        aria-label="Delete session"
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
