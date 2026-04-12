"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Loader2, MessageSquare, Search, X } from "lucide-react";
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

function formatTimestamp(value?: number) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

export default function HistorySessionPicker({
  open,
  onClose,
  onApply,
}: HistorySessionPickerProps) {
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
        const data = await listSessions(200, 0);
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
      .filter((session) => selectedIds.includes(session.session_id || session.id))
      .map((session) => ({
        sessionId: session.session_id || session.id,
        title: session.title || "Untitled session",
      }));
    onApply(selected);
    onClose();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-md">
      <div className="w-full max-w-4xl overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_22px_70px_rgba(15,23,42,0.24)] dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <div>
            <div className="text-[16px] font-semibold text-slate-900 dark:text-slate-100">
              Select History Sessions
            </div>
            <div className="mt-1 text-[12px] text-slate-500 dark:text-slate-400">
              Choose one or more past conversations to analyze before this turn.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X size={18} />
          </button>
        </div>

        <div className="bg-slate-50/70 p-5 dark:bg-slate-950/40">
          <div className="mb-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search sessions by title or last message"
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-[13px] text-slate-900 outline-none transition focus:border-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
            </div>
            <button
              onClick={() => setSelectedIds([])}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[12px] font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Clear
            </button>
          </div>

          <div className="max-h-[56vh] overflow-y-auto rounded-[18px] border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            {loading ? (
              <div className="flex min-h-[280px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            ) : filteredSessions.length ? (
              <div className="divide-y divide-slate-200 dark:divide-slate-800">
                {filteredSessions.map((session) => {
                  const id = session.session_id || session.id;
                  const selected = selectedIds.includes(id);
                  return (
                    <button
                      key={id}
                      onClick={() => toggleSession(session)}
                      className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-800/60"
                    >
                      <div
                        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                          selected
                            ? "border-indigo-500 bg-indigo-500 text-white"
                            : "border-slate-300 text-transparent dark:border-slate-600"
                        }`}
                      >
                        <Check size={12} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1 rounded-md bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                            <MessageSquare size={11} />
                            History
                          </span>
                          <span className="truncate text-[14px] font-medium text-slate-900 dark:text-slate-100">
                            {session.title || "Untitled session"}
                          </span>
                        </div>
                        {session.last_message ? (
                          <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-slate-500 dark:text-slate-400">
                            {session.last_message}
                          </p>
                        ) : null}
                        <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-400 dark:text-slate-500">
                          <span>{session.message_count ?? 0} messages</span>
                          <span>{formatTimestamp(session.updated_at)}</span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-6 py-14 text-center text-[13px] text-slate-500 dark:text-slate-400">
                No matching sessions found.
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between">
            <div className="text-[12px] text-slate-500 dark:text-slate-400">
              {selectedIds.length} session{selectedIds.length === 1 ? "" : "s"} selected
            </div>
            <button
              onClick={handleApply}
              disabled={!selectedIds.length}
              className="rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition disabled:cursor-not-allowed disabled:opacity-40"
            >
              Use Selected Sessions ({selectedIds.length})
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
