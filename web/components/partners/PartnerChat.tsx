"use client";

/**
 * Web chat with a partner over `WS /api/v1/partners/{id}/ws`.
 *
 * The socket forwards every chat-loop StreamEvent verbatim (`stream_event`
 * frames carry the backend event's `to_dict()`, which IS the frontend
 * `StreamEvent` shape), so this reuses product chat's rendering wholesale:
 * `AssistantActivity` shows the live thinking/tool trace (open while
 * working, collapsed once answered) and the answer text is recomputed with
 * the same narration-demotion rules as chat.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import dynamic from "next/dynamic";
import { Paperclip } from "lucide-react";
import { wsUrl } from "@/lib/api";
import {
  archivePartnerSession,
  branchPartnerSession,
  deletePartnerSession,
  getPartnerHistory,
  getPartnerSessions,
  resumePartnerSession,
} from "@/lib/partners-api";
import { freshPartnerSessionKey } from "@/lib/partner-session";
import type { ExportableMessage } from "@/lib/chat-export";
import type { StreamEvent } from "@/lib/unified-ws";
import { docIconFor, formatBytes, isSvgFilename } from "@/lib/doc-attachments";
import {
  isNarrationMarker,
  recomputeAnswerContent,
  shouldAppendEventContent,
} from "@/lib/stream";
import { AssistantActivity } from "@/components/chat/home/TracePanels";
import {
  PartnerComposer,
  type PartnerPendingAttachment,
} from "@/components/partners/PartnerComposer";
import PartnerAvatar from "@/components/partners/PartnerAvatar";

const AssistantResponse = dynamic(
  () => import("@/components/common/AssistantResponse"),
  { ssr: false },
);

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  attachments?: PartnerMessageAttachment[];
  /** Full turn event stream (live turns only; restored history has none). */
  events?: StreamEvent[];
  error?: boolean;
}

interface PartnerMessageAttachment {
  type: string;
  filename: string;
  mimeType?: string;
  size?: number;
  previewUrl?: string;
}

// Commands the web client handles itself (they change client state — the
// active session, or the in-flight turn — which a server text reply can't do).
const CLIENT_COMMANDS = new Set([
  "/new",
  "/clear",
  "/branch",
  "/resume",
  "/delete",
  "/sessions",
  "/stop",
]);

function parseClientCommand(
  content: string,
): { command: string; arg: string } | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith("/")) return null;
  const [head, ...rest] = trimmed.split(/\s+/);
  const command = head.toLowerCase();
  if (!CLIENT_COMMANDS.has(command)) return null;
  return { command, arg: rest.join(" ").trim() };
}

function normalizeHistoryEvents(value: unknown): StreamEvent[] | undefined {
  if (!Array.isArray(value) || value.length === 0) return undefined;
  return value as StreamEvent[];
}

function normalizeHistoryAttachments(
  value: unknown,
): PartnerMessageAttachment[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item): PartnerMessageAttachment | null => {
      if (!item || typeof item !== "object") return null;
      const obj = item as Record<string, unknown>;
      const filename = String(obj.filename || "");
      if (!filename) return null;
      const sizeRaw = obj.size;
      return {
        type: String(obj.type || "file"),
        filename,
        mimeType: String(obj.mime_type || obj.mimeType || ""),
        size: typeof sizeRaw === "number" ? sizeRaw : undefined,
      };
    })
    .filter((item): item is PartnerMessageAttachment => item !== null);
}

function sentAttachmentsForMessage(
  attachments: PartnerPendingAttachment[],
): PartnerMessageAttachment[] {
  return attachments.map((item) => ({
    type: item.type,
    filename: item.filename,
    mimeType: item.mimeType,
    size: item.size,
    previewUrl: item.previewUrl,
  }));
}

function AttachmentStrip({
  attachments,
}: {
  attachments?: PartnerMessageAttachment[];
}) {
  if (!attachments?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {attachments.map((attachment, index) => {
        if (
          (attachment.type === "image" || isSvgFilename(attachment.filename)) &&
          attachment.previewUrl
        ) {
          return (
            <div
              key={`${attachment.filename}-${index}`}
              className="h-14 w-14 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--muted)]/35"
              title={attachment.filename}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={attachment.previewUrl}
                alt={attachment.filename}
                className={`h-full w-full ${isSvgFilename(attachment.filename) ? "object-contain p-1" : "object-cover"}`}
              />
            </div>
          );
        }

        const spec = docIconFor(attachment.filename);
        const Icon = spec.Icon;
        const sizeLabel = attachment.size ? formatBytes(attachment.size) : "";
        return (
          <div
            key={`${attachment.filename}-${index}`}
            className="flex max-w-[190px] items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)]/80 px-2 py-1.5"
            title={attachment.filename}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/60">
              {attachment.filename ? (
                <Icon size={15} strokeWidth={1.5} className={spec.tint} />
              ) : (
                <Paperclip className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11px] font-medium text-[var(--foreground)]">
                {attachment.filename}
              </div>
              <div className="truncate text-[9px] uppercase text-[var(--muted-foreground)]">
                {sizeLabel ? `${spec.label} · ${sizeLabel}` : spec.label}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function PartnerChat({
  partnerId,
  partnerName,
  emoji,
  color,
  avatar,
  running,
  sessionKey,
  onSessionKeyChange,
  onToast,
  onMessagesChange,
}: {
  partnerId: string;
  partnerName: string;
  emoji?: string;
  color?: string;
  avatar?: string;
  running: boolean;
  /** The active web session key (canonical id), owned by the page so the
   *  Archive tab can switch which conversation the Chat tab is on. */
  sessionKey: string;
  /** Rotate to a different session (new / branch / resume / delete-current). */
  onSessionKeyChange: (key: string) => void;
  onToast?: (message: string) => void;
  /** Lifts the settled conversation up so the page header can export it.
   *  Fires only on discrete message events (send / turn done / clear), not
   *  per streamed token — the live `draft` is intentionally excluded. */
  onMessagesChange?: (messages: ExportableMessage[]) => void;
}) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [connected, setConnected] = useState(false);
  // Live turn snapshot for rendering. The authoritative accumulator is a
  // local variable inside the socket effect (event handlers may mutate it
  // freely); every frame publishes a fresh snapshot object here.
  const [draft, setDraft] = useState<{
    events: StreamEvent[];
    content: string;
  } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Mirror the active session into a ref so the socket's onopen (which closes
  // over the effect's first render) attaches to the CURRENT session.
  const sessionKeyRef = useRef(sessionKey);
  sessionKeyRef.current = sessionKey;
  // Attach to an in-flight turn only AFTER history has loaded, so the replay's
  // echoed question + answer aren't clobbered by the history replace. Attach
  // once per socket connection.
  const historyReadyRef = useRef(false);
  const attachedRef = useRef(false);

  const tryAttach = useCallback(() => {
    if (attachedRef.current) return;
    if (!historyReadyRef.current || !sessionKeyRef.current) return;
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    attachedRef.current = true;
    wsRef.current.send(
      JSON.stringify({ action: "attach", session_key: sessionKeyRef.current }),
    );
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior,
      });
    });
  }, []);

  // Restore the active session's history (scoped to it — the cross-channel
  // "memory feel" is served by the read_memory tool now, not by merging raw
  // transcripts). Re-runs when the page switches the active session (resume /
  // branch). Persisted turn events rehydrate the collapsible "Done" activity.
  useEffect(() => {
    if (!sessionKey) return;
    let cancelled = false;
    historyReadyRef.current = false;
    void getPartnerHistory(partnerId, {
      sessionKey,
      limit: 60,
    })
      .then((history) => {
        if (cancelled) return;
        setMessages(
          history
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({
              role: m.role as "user" | "assistant",
              content: m.content,
              attachments: normalizeHistoryAttachments(
                (m as Record<string, unknown>).attachments,
              ),
              events: normalizeHistoryEvents(
                (m as Record<string, unknown>).events,
              ),
            })),
        );
        historyReadyRef.current = true;
        tryAttach();
        requestAnimationFrame(() => scrollToBottom("instant"));
      })
      .catch(() => {
        historyReadyRef.current = true;
        tryAttach();
      });
    return () => {
      cancelled = true;
    };
  }, [partnerId, sessionKey, scrollToBottom, tryAttach]);

  useEffect(() => {
    if (!running) {
      wsRef.current?.close();
      wsRef.current = null;
      setConnected(false);
      setStreaming(false);
      setDraft(null);
      return;
    }

    attachedRef.current = false;
    const ws = new WebSocket(wsUrl(`/api/v1/partners/${partnerId}/ws`));
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      // Reattach to an in-flight turn (survives a page refresh): the server
      // replays its buffered stream, so a mid-answer reload keeps streaming.
      // Sequenced after history load via tryAttach so the replay isn't
      // clobbered by the history replace.
      tryAttach();
    };

    // Authoritative live-turn accumulator. Lives in the effect scope so
    // socket handlers can mutate it cheaply; renders see snapshots only.
    let live: { events: StreamEvent[]; content: string } | null = null;
    const publish = () => {
      setDraft(
        live ? { events: [...live.events], content: live.content } : null,
      );
    };

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data) as {
        type: string;
        content?: string;
        event?: StreamEvent;
      };
      if (data.type === "resuming") {
        // Server is about to replay an in-flight turn (after a refresh).
        live = { events: [], content: "" };
        setStreaming(true);
        publish();
        return;
      }
      if (data.type === "user_echo") {
        // The question that opened the replayed turn (not yet persisted).
        setMessages((msgs) => [
          ...msgs,
          { role: "user", content: data.content ?? "" },
        ]);
        scrollToBottom();
        return;
      }
      if (data.type === "stream_event" && data.event) {
        const event = data.event;
        live ??= { events: [], content: "" };
        live.events.push(event);
        if (shouldAppendEventContent(event)) {
          live.content += event.content;
        } else if (isNarrationMarker(event)) {
          // A round resolved as narration — its streamed text belongs to
          // the trace, not the answer. Same demotion rule as product chat.
          live.content = recomputeAnswerContent(live.events);
        }
        publish();
        scrollToBottom();
      } else if (data.type === "content") {
        // Authoritative final text from the runner (covers terminator /
        // ask_user fallbacks the client-side recompute can't know about).
        const finished = live;
        live = null;
        setMessages((msgs) => [
          ...msgs,
          {
            role: "assistant",
            content: data.content || finished?.content || "",
            events: finished?.events.length ? finished.events : undefined,
          },
        ]);
        publish();
        scrollToBottom();
      } else if (data.type === "done") {
        setStreaming(false);
        live = null;
        publish();
      } else if (data.type === "stopped") {
        // Server cancelled the turn (/stop or the stop button). Keep any
        // partial answer the user already saw; drop the live draft.
        const finished = live;
        live = null;
        if (finished && (finished.content || finished.events.length)) {
          setMessages((msgs) => [
            ...msgs,
            {
              role: "assistant",
              content: finished.content,
              events: finished.events.length ? finished.events : undefined,
            },
          ]);
        }
        setStreaming(false);
        publish();
      } else if (data.type === "proactive") {
        setMessages((msgs) => [
          ...msgs,
          { role: "assistant", content: data.content ?? "" },
        ]);
        scrollToBottom();
      } else if (data.type === "error") {
        setMessages((msgs) => [
          ...msgs,
          { role: "assistant", content: data.content ?? "Error", error: true },
        ]);
        live = null;
        publish();
        setStreaming(false);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setStreaming(false);
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [partnerId, running, scrollToBottom, tryAttach]);

  // Report the settled transcript to the parent for header export controls.
  useEffect(() => {
    onMessagesChange?.(
      messages.map((msg) => ({
        role: msg.role,
        content: msg.content,
        attachments: msg.attachments?.map((a) => ({
          type: a.type,
          filename: a.filename,
          mime_type: a.mimeType,
        })),
      })),
    );
  }, [messages, onMessagesChange]);

  const sendStop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ action: "stop", session_key: sessionKey }),
      );
    }
  }, [sessionKey]);

  // Session-management commands run client-side: they switch the active
  // session or stop the turn — things a server text reply can't do. Returns
  // true when handled (so the caller skips the normal send).
  const runClientCommand = useCallback(
    async (command: string, arg: string): Promise<void> => {
      switch (command) {
        case "/new":
        case "/clear": {
          await archivePartnerSession(partnerId, sessionKey).catch(() => {});
          setMessages([]);
          onSessionKeyChange(freshPartnerSessionKey());
          break;
        }
        case "/branch": {
          const next = freshPartnerSessionKey();
          try {
            await branchPartnerSession(partnerId, sessionKey, next);
            onToast?.(
              t("Branched — the original is archived as {{id}}", {
                id: sessionKey,
              }),
            );
            onSessionKeyChange(next); // history reload picks up the copy
          } catch {
            onToast?.(t("Nothing to branch yet."));
          }
          break;
        }
        case "/resume": {
          if (!arg) {
            onToast?.(t("Usage: /resume <session ID>"));
            break;
          }
          try {
            await resumePartnerSession(partnerId, arg);
            onSessionKeyChange(arg);
          } catch {
            onToast?.(t("Session not found"));
          }
          break;
        }
        case "/delete": {
          if (!arg) {
            onToast?.(t("Usage: /delete <session ID>"));
            break;
          }
          try {
            await deletePartnerSession(partnerId, arg);
            onToast?.(t("Conversation deleted"));
            if (arg === sessionKey) {
              setMessages([]);
              onSessionKeyChange(freshPartnerSessionKey());
            }
          } catch {
            onToast?.(t("Session not found"));
          }
          break;
        }
        case "/sessions": {
          try {
            const sessions = await getPartnerSessions(partnerId);
            const lines = sessions
              .slice(0, 30)
              .map(
                (s) =>
                  `- \`${s.session_key}\`${s.archived ? ` (${t("Archived")})` : ""} — ${
                    s.title || t("New conversation")
                  } · ${s.message_count}`,
              )
              .join("\n");
            setMessages((msgs) => [
              ...msgs,
              {
                role: "assistant",
                content: `${t("Conversations:")}\n${lines}\n\n${t(
                  "Use /resume <session ID> or /delete <session ID>.",
                )}`,
              },
            ]);
            scrollToBottom();
          } catch {
            onToast?.(t("Load failed"));
          }
          break;
        }
        case "/stop": {
          sendStop();
          break;
        }
      }
    },
    [
      partnerId,
      sessionKey,
      onSessionKeyChange,
      onToast,
      scrollToBottom,
      sendStop,
      t,
    ],
  );

  const handleSend = useCallback(
    (content: string, attachments: PartnerPendingAttachment[]) => {
      if (streaming || !running) return;

      const command =
        attachments.length === 0 ? parseClientCommand(content) : null;
      if (command) {
        void runClientCommand(command.command, command.arg);
        return;
      }

      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const visibleContent =
        content ||
        (attachments.every((item) => item.type === "image")
          ? t("Please analyze the attached image(s).")
          : t("Please use the attached file(s)."));
      wsRef.current.send(
        JSON.stringify({
          content: visibleContent,
          session_key: sessionKey,
          attachments: attachments.map((item) => ({
            type: item.type,
            filename: item.filename,
            base64: item.base64,
            mime_type: item.mimeType,
          })),
        }),
      );
      setMessages((msgs) => [
        ...msgs,
        {
          role: "user",
          content: visibleContent,
          attachments: sentAttachmentsForMessage(attachments),
        },
      ]);
      setDraft({ events: [], content: "" });
      setStreaming(true);
      scrollToBottom();
    },
    [sessionKey, running, streaming, scrollToBottom, runClientCommand, t],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-1 py-4">
        {messages.length === 0 && !draft ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <PartnerAvatar
              name={partnerName}
              emoji={emoji}
              color={color}
              image={avatar}
              size={56}
            />
            <div>
              <p className="text-[15px] font-medium text-[var(--foreground)]">
                {partnerName}
              </p>
              <p className="mt-1 max-w-sm text-[12.5px] text-[var(--muted-foreground)]">
                {running
                  ? t(
                      "Say hello — this conversation shares the same memory your partner has on its connected channels.",
                    )
                  : t("Partner is stopped. Start it before chatting.")}
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-5">
            {messages.map((msg, i) =>
              msg.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[75%] rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm">
                    {msg.content ? (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    ) : null}
                    <AttachmentStrip attachments={msg.attachments} />
                  </div>
                </div>
              ) : (
                <div key={i} className="flex items-start gap-2.5">
                  <PartnerAvatar
                    name={partnerName}
                    emoji={emoji}
                    color={color}
                    size={26}
                  />
                  <div className="min-w-0 flex-1">
                    {msg.events && msg.events.length > 0 && (
                      <AssistantActivity
                        events={msg.events}
                        isStreaming={false}
                        content={msg.content}
                        className="mb-1.5"
                        agentName={partnerName}
                        showMark={false}
                        headerClassName="min-h-[26px]"
                      />
                    )}
                    {msg.error ? (
                      <p className="text-[13px] text-[var(--destructive)]">
                        {msg.content}
                      </p>
                    ) : (
                      <AssistantResponse content={msg.content} />
                    )}
                  </div>
                </div>
              ),
            )}

            {draft && (
              <div className="flex items-start gap-2.5">
                <PartnerAvatar
                  name={partnerName}
                  emoji={emoji}
                  color={color}
                  size={26}
                />
                <div className="min-w-0 flex-1">
                  <AssistantActivity
                    events={draft.events}
                    isStreaming
                    content={draft.content}
                    className="mb-1.5"
                    agentName={partnerName}
                    showMark={false}
                    headerClassName="min-h-[26px]"
                  />
                  {draft.content ? (
                    <AssistantResponse content={draft.content} />
                  ) : null}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-2xl px-1 pb-4">
        {!running ? (
          <p className="mb-1 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Partner is stopped. Start it before chatting.")}
          </p>
        ) : !connected ? (
          <p className="mb-1 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Connecting…")}
          </p>
        ) : null}
        <PartnerComposer
          onSend={handleSend}
          onStop={sendStop}
          streaming={streaming}
          disabled={!connected || !running}
        />
      </div>
    </div>
  );
}
