"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  History as HistoryIcon,
  Loader2,
  MessageSquare,
  Search,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { listSessions, type SessionSummary } from "@/lib/session-api";

export interface SelectedHistorySession {
  sessionId: string;
  title: string;
}

interface HistorySessionPickerProps {
  open: boolean;
  onClose: () => void;
  onApply: (sessions: SelectedHistorySession[]) => void;
}

/**
 * Format a backend session timestamp (stored as float seconds via time.time())
 * into a localized string. Returns an empty string when the timestamp is
 * missing or non-positive so we don't render nonsensical 1970 dates.
 */
function formatSessionTimestamp(value?: number): string {
  if (!value || value <= 0) return "";
  // Backend stores REAL seconds. JS Date expects milliseconds.
  return new Date(value * 1000).toLocaleString();
}

export default function HistorySessionPicker({
  open,
  onClose,
  onApply,
}: HistorySessionPickerProps) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;

    let mounted = true;
    const load = async () => {
      setLoading(true);
      try {
        const data = await listSessions(200, 0, { force: true });
        if (!mounted) return;
        setSessions(data);
      } catch {
        if (!mounted) return;
        setSessions([]);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    void load();
    return () => {
      mounted = false;
    };
  }, [open]);

  const filteredSessions = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return sessions;
    return sessions.filter((session) => {
      const title = String(session.title || "").toLowerCase();
      const lastMessage = String(session.last_message || "").toLowerCase();
      return title.includes(keyword) || lastMessage.includes(keyword);
    });
  }, [query, sessions]);

  const toggleSession = (session: SessionSummary) => {
    const id = session.session_id || session.id;
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const handleApply = () => {
    const selected = sessions
      .filter((session) =>
        selectedIds.includes(session.session_id || session.id),
      )
      .map((session) => ({
        sessionId: session.session_id || session.id,
        title: session.title || "Untitled session",
      }));
    onApply(selected);
    onClose();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[85] flex items-end justify-center bg-[var(--background)]/65 p-0 backdrop-blur-md sm:items-center sm:p-4">
      <div className="surface-card flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-t-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)] sm:rounded-2xl">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--border)] px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <div className="mb-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--primary)]">
              <HistoryIcon className="h-3 w-3" />
              {t("Chat History Reference")}
            </div>
            <h2 className="text-lg font-semibold text-[var(--foreground)]">
              {t("Select History Sessions")}
            </h2>
            <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
              {t(
                "Choose one or more past conversations to analyze before this turn.",
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label={t("Close")}
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col bg-[var(--background)]/40 p-4 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search sessions by title or last message")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
              />
            </div>
            <button
              onClick={() => setSelectedIds([])}
              className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {t("Clear")}
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)]">
            {loading ? (
              <div className="flex min-h-[280px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : filteredSessions.length ? (
              <div className="divide-y divide-[var(--border)]">
                {filteredSessions.map((session) => {
                  const id = session.session_id || session.id;
                  const selected = selectedIds.includes(id);
                  const timestamp = formatSessionTimestamp(
                    session.updated_at || session.created_at,
                  );
                  return (
                    <button
                      key={id}
                      onClick={() => toggleSession(session)}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
                        selected
                          ? "bg-[var(--primary)]/8"
                          : "hover:bg-[var(--muted)]/40"
                      }`}
                    >
                      <div
                        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                          selected
                            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "border-[var(--border)] text-transparent"
                        }`}
                      >
                        <Check size={12} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1 rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)]">
                            <MessageSquare size={11} />
                            {t("History")}
                          </span>
                          <span className="truncate text-[14px] font-medium text-[var(--foreground)]">
                            {session.title || t("Untitled session")}
                          </span>
                        </div>
                        {session.last_message ? (
                          <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
                            {session.last_message}
                          </p>
                        ) : null}
                        <div className="mt-2 flex items-center gap-3 text-[11px] text-[var(--muted-foreground)]/85">
                          <span>
                            {session.message_count ?? 0} {t("messages")}
                          </span>
                          {timestamp && <span>{timestamp}</span>}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-6 py-14 text-center text-[13px] text-[var(--muted-foreground)]">
                {t("No matching sessions found.")}
              </div>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-[12px] text-[var(--muted-foreground)]">
              {selectedIds.length === 1
                ? t("1 session selected")
                : t("{n} sessions selected", { n: selectedIds.length })}
            </div>
            <button
              onClick={handleApply}
              disabled={!selectedIds.length}
              className="btn-primary rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("Use Selected Sessions ({n})", { n: selectedIds.length })}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
