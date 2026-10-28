"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Clock3,
  MessageSquareText,
  User,
  Users,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { fromMarkdown } from "mdast-util-from-markdown";
import {
  deletePartnerSession,
  getPartnerHistoryPage,
  getPartnerSessions,
  resumePartnerSession,
  type PartnerSessionInfo,
} from "@/lib/partners-api";
import type { ExportableMessage } from "@/lib/chat-export";
import { plainTextPreview } from "@/lib/chat-outline";
import { displaySessionTitle } from "@/lib/session-title";
import AssistantResponse from "@/components/common/AssistantResponse";
import { InlineFileCardProvider } from "@/components/common/InlineFileCard";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import Tooltip from "@/shared/ui/Tooltip";

interface HistoryMessage {
  role: string;
  content: string;
  timestamp?: string;
  channel?: string;
  attachments?: Record<string, unknown>[];
}

function historyAttachments(attachments?: Record<string, unknown>[]): MessageAttachment[] {
  return (attachments ?? []).flatMap((attachment): MessageAttachment[] => {
    if (
      typeof attachment.type !== "string" ||
      typeof attachment.filename !== "string" ||
      typeof attachment.url !== "string" ||
      (attachment.generated !== true && attachment.origin !== "workspace")
    ) return [];
    return [{
      type: attachment.type,
      filename: attachment.filename,
      url: attachment.url,
      generated: attachment.generated === true,
      origin: attachment.origin === "workspace" ? "workspace" : undefined,
      relative_path: typeof attachment.relative_path === "string" ? attachment.relative_path : undefined,
      title: typeof attachment.title === "string" ? attachment.title : undefined,
    }];
  });
}

function conversationPreview(content: string): string {
  const tableCells = (line: string): string[] | null => {
    const cells = [""];
    let hasPipe = false;
    for (let index = 0; index < line.length; index++) {
      const character = line[index];
      if (character === "\\" && index + 1 < line.length) {
        cells[cells.length - 1] += character + line[++index];
      } else if (character === "|") {
        hasPipe = true;
        cells.push("");
      } else {
        cells[cells.length - 1] += character;
      }
    }
    if (!hasPipe) return null;
    if (!cells[0].trim()) cells.shift();
    if (!cells.at(-1)?.trim()) cells.pop();
    return cells.map((cell) => cell.trim());
  };
  const lines = content.split("\n");
  const rows = lines.map(tableCells);
  let inTable = false;
  let separatorIndex = -1;
  let text = lines
    .map((line, index) => {
      if (index === separatorIndex) return "";
      const cells = rows[index];
      const next = rows[index + 1];
      if (!inTable && cells?.length && next?.length === cells.length && next.every((cell) => /^:?-+:?$/.test(cell))) {
        inTable = true;
        separatorIndex = index + 1;
      }
      if (inTable && cells) {
        return cells.map((cell) => cell.replace(/\\\|/g, "|")).join(" · ");
      }
      inTable = false;
      return line;
    })
    .join("\n");

  // Keep code literal through all Markdown cleanup, including multi-backtick spans.
  const literals = new Map<string, string>();
  const tree = fromMarkdown(text);
  const pending: (typeof tree | (typeof tree.children)[number])[] = [tree];
  let markerCode = 0xe000;
  while (pending.length) {
    const node = pending.pop()!;
    if (node.type === "inlineCode") {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (start === undefined || end === undefined) continue;
      let marker = String.fromCharCode(markerCode++);
      while (text.includes(marker)) marker = String.fromCharCode(markerCode++);
      literals.set(marker, node.value.replace(/\r\n?|\n/g, " "));
      text = text.slice(0, start) + marker + text.slice(end);
    } else if ("children" in node) {
      // Visit right to left so replacing a code span preserves earlier offsets.
      pending.push(...node.children);
    }
  }
  // The server may truncate the snippet before an emphasis delimiter closes.
  const repaired = text.replace(
    /(\*\*|__|~~).*?\1|(?<![\w\\])(?:\*\*|__|~~)(?=\S)/g,
    (match, paired) => paired ? match : "",
  );
  const preview = plainTextPreview(repaired, Infinity).replace(
    /[\ue000-\uf8ff]/g,
    (marker) => literals.get(marker) ?? marker,
  );
  return preview.length > 160 ? `${preview.slice(0, 160).trimEnd()}…` : preview;
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function PartnerArchives({
  partnerId,
  onToast,
  onMessagesChange,
  onResume,
  onDeleted,
}: {
  partnerId: string;
  onToast: (message: string) => void;
  /** Lifts the selected conversation up so the page header can export it.
   *  Empty array when nothing is selected (or while loading). */
  onMessagesChange?: (messages: ExportableMessage[]) => void;
  /** Continue a conversation in the Chat tab (un-archives it first). */
  onResume?: (sessionKey: string, activeKey: string | null, didCallResume: boolean) => void;
  /** The page owns both its local key and its shared selection. */
  onDeleted?: (sessionKey: string, activeKey: string | null) => void;
}) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<PartnerSessionInfo[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [olderBefore, setOlderBefore] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const messageScrollRef = useRef<HTMLDivElement>(null);
  const selectedKeyRef = useRef(selectedKey);
  selectedKeyRef.current = selectedKey;

  const downloadGeneratedAttachment = useCallback((attachment: MessageAttachment) => {
    if (!attachment.url) return;
    const link = document.createElement("a");
    link.href = attachment.url;
    link.download = attachment.filename || "download";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, []);

  const selected = useMemo(
    () =>
      sessions.find((session) => session.session_key === selectedKey) ?? null,
    [sessions, selectedKey],
  );

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const next = await getPartnerSessions(partnerId);
      setSessions(next);
      setSelectedKey((current) => {
        if (
          current &&
          next.some((session) => session.session_key === current)
        ) {
          return current;
        }
        return next[0]?.session_key ?? "";
      });
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Load failed"));
    } finally {
      setLoadingSessions(false);
    }
  }, [partnerId, onToast, t]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const handleResume = useCallback(
    async (session: PartnerSessionInfo) => {
      try {
        const result = session.archived
          ? await resumePartnerSession(partnerId, session.session_key)
          : null;
        onResume?.(session.session_key, result?.active_session_key ?? null, result !== null);
      } catch (e) {
        onToast(e instanceof Error ? e.message : t("Load failed"));
      }
    },
    [partnerId, onResume, onToast, t],
  );

  const handleDelete = useCallback(
    async (session: PartnerSessionInfo) => {
      try {
        const result = await deletePartnerSession(partnerId, session.session_key);
        onDeleted?.(session.session_key, result.active_session_key);
        if (selectedKey === session.session_key) setSelectedKey("");
        onToast(t("Conversation deleted"));
        await loadSessions();
      } catch (e) {
        onToast(e instanceof Error ? e.message : t("Delete failed"));
      }
    },
    [partnerId, selectedKey, loadSessions, onToast, onDeleted, t],
  );

  useEffect(() => {
    if (!selectedKey) {
      setMessages([]);
      setOlderBefore(null);
      return;
    }
    let cancelled = false;
    setLoadingMessages(true);
    setLoadingOlder(false);
    setMessages([]);
    setOlderBefore(null);
    void getPartnerHistoryPage(partnerId, selectedKey, { limit: 100 })
      .then((page) => {
        if (!cancelled) {
          setMessages(page.messages);
          setOlderBefore(page.next_before);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setMessages([]);
          onToast(e instanceof Error ? e.message : t("Load failed"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingMessages(false);
      });
    return () => {
      cancelled = true;
    };
  }, [partnerId, selectedKey, onToast, t]);

  const loadOlder = useCallback(async () => {
    if (!selectedKey || olderBefore === null || loadingOlder) return;
    const container = messageScrollRef.current;
    const previousHeight = container?.scrollHeight ?? 0;
    const previousTop = container?.scrollTop ?? 0;
    setLoadingOlder(true);
    try {
      const page = await getPartnerHistoryPage(partnerId, selectedKey, {
        before: olderBefore,
        limit: 100,
      });
      if (selectedKeyRef.current !== selectedKey) return;
      setMessages((current) => [...page.messages, ...current]);
      setOlderBefore(page.next_before);
      requestAnimationFrame(() => {
        if (selectedKeyRef.current === selectedKey && container) {
          container.scrollTop = previousTop + container.scrollHeight - previousHeight;
        }
      });
    } catch (error) {
      onToast(error instanceof Error ? error.message : t("Load failed"));
    } finally {
      if (selectedKeyRef.current === selectedKey) setLoadingOlder(false);
    }
  }, [selectedKey, olderBefore, loadingOlder, partnerId, onToast, t]);

  // Report the selected conversation up for header export controls.
  useEffect(() => {
    if (!onMessagesChange) return;
    if (!selectedKey || loadingMessages) {
      onMessagesChange([]);
      return;
    }
    onMessagesChange(
      messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content })),
    );
  }, [messages, selectedKey, loadingMessages, onMessagesChange]);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <div className="min-h-0 border-r border-[var(--border)] pr-4 lg:overflow-y-auto">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <h2 className="text-[13px] font-medium text-[var(--foreground)]">
              {t("Conversations")}
            </h2>
            <p className="text-[11.5px] text-[var(--muted-foreground)]">
              {sessions.length
                ? t("{{count}} session(s)", { count: sessions.length })
                : t("No sessions")}
            </p>
          </div>
          <Tooltip label={t("Refresh")}>
            <button
              type="button"
              onClick={() => void loadSessions()}
              disabled={loadingSessions}
              aria-label={t("Refresh")}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${loadingSessions ? "animate-spin" : ""}`}
              />
            </button>
          </Tooltip>
        </div>

        <div className="space-y-2">
          {sessions.map((session) => (
            <button
              key={session.session_key}
              type="button"
              onClick={() => setSelectedKey(session.session_key)}
              className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                selectedKey === session.session_key
                  ? "border-[var(--ring)] bg-[var(--muted)]"
                  : "border-[var(--border)] hover:border-[var(--ring)]"
              }`}
            >
              <div className="flex items-center gap-2">
                {session.archived ? (
                  <Archive className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
                ) : (
                  <MessageSquareText className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
                )}
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                  {displaySessionTitle(
                    session.title,
                    session.archived ? t("Archived") : t("New conversation"),
                  )}
                </span>
                <span className="text-[11px] text-[var(--muted-foreground)]">
                  {session.message_count}
                </span>
              </div>
              {session.last_message ? (
                <p className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                  {conversationPreview(session.last_message)}
                </p>
              ) : null}
              <div className="mt-1 flex items-center gap-2 text-[10.5px] text-[var(--muted-foreground)]">
                <span className="flex items-center gap-1">
                  <Clock3 className="h-3 w-3" />
                  {formatTime(session.updated_at)}
                </span>
                {/* Which conversation on the platform this came from. One
                    partner commonly serves several study groups plus DMs, and
                    without this every one of them reads as a private chat
                    (#1229). Sessions recorded before the origin was stored
                    carry none, and simply show nothing extra. */}
                {session.chat_id ? (
                  <span
                    className="flex min-w-0 items-center gap-1"
                    title={session.chat_id}
                  >
                    {session.scope === "group" ? (
                      <Users className="h-3 w-3 shrink-0" />
                    ) : session.scope === "direct" ? (
                      <User className="h-3 w-3 shrink-0" />
                    ) : null}
                    <span className="truncate">{session.chat_id}</span>
                  </span>
                ) : null}
              </div>
            </button>
          ))}
          {!loadingSessions && sessions.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] px-3 py-8 text-center text-[12px] text-[var(--muted-foreground)]">
              {t("No conversations yet")}
            </div>
          ) : null}
        </div>
      </div>

      <div ref={messageScrollRef} className="min-h-0 overflow-y-auto">
        {selected ? (
          <div className="mx-auto max-w-2xl pb-4">
            <div className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--background)] py-2">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-[13px] font-medium text-[var(--foreground)]">
                    {displaySessionTitle(
                      selected.title,
                      selected.archived
                        ? t("Archived conversation")
                        : t("New conversation"),
                    )}
                  </h3>
                  <p className="text-[11.5px] text-[var(--muted-foreground)]">
                    {(selected.archived ? `${t("Archived")} · ` : "") +
                      formatTime(selected.updated_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="rounded-md bg-[var(--muted)] px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
                    {t("{{count}} messages", { count: selected.message_count })}
                  </span>
                  <Tooltip label={t("Continue this conversation")}>
                    <button
                      type="button"
                      onClick={() => void handleResume(selected)}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--foreground)] hover:bg-[var(--muted)]"
                    >
                      <RotateCcw className="h-3 w-3" />
                      {t("Continue")}
                    </button>
                  </Tooltip>
                  <Tooltip label={t("Delete conversation")}>
                    <button
                      type="button"
                      onClick={() => void handleDelete(selected)}
                      aria-label={t("Delete conversation")}
                      className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-red-500"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </Tooltip>
                </div>
              </div>
            </div>

            <div className="space-y-4 py-4">
              {olderBefore !== null && !loadingMessages ? (
                <button
                  type="button"
                  onClick={() => void loadOlder()}
                  disabled={loadingOlder}
                  className="mx-auto block rounded-md border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                >
                  {loadingOlder ? t("Loading...") : t("Load older messages")}
                </button>
              ) : null}
              {loadingMessages ? (
                <p className="text-[12px] text-[var(--muted-foreground)]">
                  {t("Loading...")}
                </p>
              ) : (
                messages
                  .filter(
                    (message) =>
                      message.role === "user" || message.role === "assistant",
                  )
                  .map((message, index) => (
                    <div
                      key={`${message.timestamp ?? index}-${index}`}
                      className={
                        message.role === "user"
                          ? "flex justify-end"
                          : "flex justify-start"
                      }
                    >
                      <div
                        className={`min-w-0 rounded-lg px-3 py-2 text-[13px] leading-relaxed ${
                          message.role === "user"
                            ? "max-w-[78%] whitespace-pre-wrap bg-[var(--secondary)] text-[var(--foreground)]"
                            : "max-w-full border border-[var(--border)] text-[var(--foreground)]"
                        }`}
                      >
                        {message.role === "assistant" ? (
                          <InlineFileCardProvider
                            attachments={historyAttachments(message.attachments)}
                            onOpen={downloadGeneratedAttachment}
                            unresolvedRelativeLinksAsText
                          >
                            <AssistantResponse content={message.content} />
                          </InlineFileCardProvider>
                        ) : message.content}
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-[12px] text-[var(--muted-foreground)]">
            {t("Select a conversation")}
          </div>
        )}
      </div>
    </div>
  );
}
