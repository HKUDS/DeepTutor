"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  History as HistoryIcon,
  Loader2,
  MessageSquare,
  Search,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import {
  getSession,
  listSessions,
  type SessionDetail,
  type SessionSummary,
} from "@/lib/session-api";
import { normalizeMessageContent, truncateText } from "@/lib/message-content";

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

function sessionKey(session: SessionSummary): string {
  return session.session_id || session.id;
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

  // The session shown in the right-hand preview pane. Driven by hover/focus
  // and click so the preview tracks wherever the user's attention is — the
  // list reads like a mail client: glide over a row, see its conversation.
  const [activeId, setActiveId] = useState<string | null>(null);
  // Fetched session transcripts, cached so re-hovering a row is instant.
  const [details, setDetails] = useState<Record<string, SessionDetail>>({});
  const detailsRef = useRef(details);
  useEffect(() => {
    detailsRef.current = details;
  }, [details]);
  const [previewLoadingId, setPreviewLoadingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;

    let mounted = true;
    const load = async () => {
      setLoading(true);
      try {
        const data = await listSessions(200, 0, { force: true });
        if (!mounted) return;
        setSessions(data);
        // Default the preview to the most recent session so the right pane is
        // never blank on open.
        setActiveId((prev) => {
          if (prev && data.some((s) => sessionKey(s) === prev)) return prev;
          return data.length ? sessionKey(data[0]) : null;
        });
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

  // Lazily fetch the active session's transcript for the preview pane.
  useEffect(() => {
    if (!open || !activeId) return;
    if (detailsRef.current[activeId]) return;
    let cancelled = false;
    setPreviewLoadingId(activeId);
    getSession(activeId)
      .then((detail) => {
        if (cancelled) return;
        setDetails((prev) => ({ ...prev, [activeId]: detail }));
      })
      .catch(() => {
        /* preview is best-effort; the list still works without it */
      })
      .finally(() => {
        if (cancelled) return;
        setPreviewLoadingId((cur) => (cur === activeId ? null : cur));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, open]);

  const filteredSessions = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return sessions;
    return sessions.filter((session) => {
      const title = String(session.title || "").toLowerCase();
      const lastMessage = normalizeMessageContent(
        session.last_message,
      ).toLowerCase();
      return title.includes(keyword) || lastMessage.includes(keyword);
    });
  }, [query, sessions]);

  const toggleSession = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const handleApply = () => {
    const selected = sessions
      .filter((session) => selectedIds.includes(sessionKey(session)))
      .map((session) => ({
        sessionId: sessionKey(session),
        title: session.title || t("Untitled session"),
      }));
    onApply(selected);
    onClose();
  };

  const activeSession = activeId
    ? sessions.find((s) => sessionKey(s) === activeId)
    : undefined;
  const activeDetail = activeId ? details[activeId] : undefined;
  const activeLoading =
    previewLoadingId !== null && previewLoadingId === activeId;

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="history-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card flex h-[78vh] max-h-[660px] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={HistoryIcon}
          titleId="history-picker-title"
          title={t("Select History Sessions")}
          subtitle={t(
            "Choose one or more past conversations to analyze before this turn.",
          )}
          onClose={onClose}
        />

        <div className="flex min-h-0 flex-1">
          {/* ── Left: searchable, selectable session list ── */}
          <div className="flex w-full min-w-0 flex-col border-r border-[var(--border)] md:w-[42%] md:max-w-[380px]">
            <div className="flex items-center gap-2 px-4 pb-3 pt-4">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("Search sessions by title or last message")}
                  className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
                />
              </div>
              {selectedIds.length > 0 && (
                <button
                  onClick={() => setSelectedIds([])}
                  className="shrink-0 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  {t("Clear")}
                </button>
              )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              {loading ? (
                <div className="flex min-h-[280px] items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : filteredSessions.length ? (
                <div className="flex flex-col gap-0.5">
                  {filteredSessions.map((session) => {
                    const id = sessionKey(session);
                    const selected = selectedIds.includes(id);
                    const active = id === activeId;
                    return (
                      <button
                        key={id}
                        onClick={() => {
                          toggleSession(id);
                          setActiveId(id);
                        }}
                        onMouseEnter={() => setActiveId(id)}
                        onFocus={() => setActiveId(id)}
                        className={`group relative flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2.5 text-left transition-colors ${
                          active
                            ? "bg-[var(--muted)]/60"
                            : selected
                              ? "bg-[var(--primary)]/[0.05] hover:bg-[var(--muted)]/40"
                              : "hover:bg-[var(--muted)]/35"
                        }`}
                      >
                        {/* Accent rail marks the previewed row */}
                        <span
                          className={`absolute inset-y-1.5 left-0 w-[2.5px] rounded-full bg-[var(--primary)] transition-opacity ${
                            active ? "opacity-100" : "opacity-0"
                          }`}
                        />
                        <span
                          className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors ${
                            selected
                              ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                              : "border-[var(--border)] text-transparent group-hover:border-[var(--muted-foreground)]/60"
                          }`}
                        >
                          <Check size={11} strokeWidth={3} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                            {session.title || t("Untitled session")}
                          </span>
                          <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]/85">
                            <MessageSquare size={11} strokeWidth={1.8} />
                            {session.message_count ?? 0} {t("messages")}
                          </span>
                        </span>
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
          </div>

          {/* ── Right: live preview of the focused session ── */}
          <div className="hidden min-w-0 flex-1 flex-col bg-[var(--background)]/30 md:flex">
            {activeSession ? (
              <>
                <div className="flex items-start justify-between gap-3 border-b border-[var(--border)]/70 px-5 py-3.5">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-semibold text-[var(--foreground)]">
                      {activeSession.title || t("Untitled session")}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2.5 text-[11px] text-[var(--muted-foreground)]">
                      <span>
                        {activeSession.message_count ?? 0} {t("messages")}
                      </span>
                      {formatSessionTimestamp(
                        activeSession.updated_at || activeSession.created_at,
                      ) && (
                        <span>
                          {formatSessionTimestamp(
                            activeSession.updated_at ||
                              activeSession.created_at,
                          )}
                        </span>
                      )}
                    </div>
                  </div>
                  {selectedIds.includes(activeId!) && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[10px] font-semibold text-[var(--primary)]">
                      <Check size={10} strokeWidth={3} />
                      {t("Selected")}
                    </span>
                  )}
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                  {activeLoading && !activeDetail ? (
                    <div className="flex min-h-[200px] items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      {t("Loading preview…")}
                    </div>
                  ) : activeDetail ? (
                    <ConversationPreview detail={activeDetail} />
                  ) : (
                    <div className="flex min-h-[200px] items-center justify-center text-[12px] text-[var(--muted-foreground)]">
                      {t("No messages in this session.")}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center text-[var(--muted-foreground)]">
                <HistoryIcon className="h-6 w-6 opacity-40" strokeWidth={1.6} />
                <p className="text-[12px]">
                  {t("Select a session to preview it here.")}
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-3.5">
          <div className="text-[12px] text-[var(--muted-foreground)]">
            {selectedIds.length === 1
              ? t("1 session selected")
              : t("{{n}} sessions selected", { n: selectedIds.length })}
          </div>
          <button
            onClick={handleApply}
            disabled={!selectedIds.length}
            className="btn-primary rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("Use Selected Sessions ({{n}})", { n: selectedIds.length })}
          </button>
        </div>
      </div>
    </PickerShell>
  );
}

/**
 * Read-only transcript rendering for the preview pane. We render the stored
 * final `content` of each message (not the streaming trace) as plain,
 * role-labelled text — enough to recognize a conversation at a glance without
 * pulling in the full markdown/KaTeX renderer.
 */
function ConversationPreview({ detail }: { detail: SessionDetail }) {
  const { t } = useTranslation();
  const turns = useMemo(
    () =>
      (detail.messages || [])
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          id: m.id,
          role: m.role,
          text: truncateText(normalizeMessageContent(m.content), 1400),
        }))
        .filter((m) => m.text.trim().length > 0),
    [detail.messages],
  );

  if (turns.length === 0) {
    return (
      <div className="flex min-h-[200px] items-center justify-center text-[12px] text-[var(--muted-foreground)]">
        {t("No messages in this session.")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {turns.map((turn) => {
        const isUser = turn.role === "user";
        return (
          <div key={turn.id}>
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">
              {isUser ? (
                <UserRound size={12} strokeWidth={1.9} />
              ) : (
                <Sparkles size={12} strokeWidth={1.9} />
              )}
              {isUser ? t("You") : t("Assistant")}
            </div>
            <div className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-[var(--foreground)]/85">
              {turn.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}
