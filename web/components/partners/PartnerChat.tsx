"use client";

/**
 * Web chat with a partner over `WS /ws/partners/{id}`.
 *
 * The socket forwards every chat-loop StreamEvent verbatim (`stream_event`
 * frames carry the backend event's `to_dict()`, which IS the frontend
 * `StreamEvent` shape), so this reuses product chat's rendering wholesale:
 * `AssistantActivity` shows the live thinking/tool trace (open while
 * working, collapsed once answered) and the answer text is recomputed with
 * the same retraction rules as chat.
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
  getPartnerHistoryPage,
  getPartnerSessions,
  resumePartnerSession,
  type PartnerHistoryMessage,
} from "@/lib/partners-api";
import { freshPartnerSessionKey } from "@/lib/partner-session";
import { displaySessionTitle } from "@/lib/session-title";
import { createPartnerDraftPublisher } from "@/lib/partner-chat-draft";
import { ReconnectingWebSocket } from "@/lib/reconnecting-websocket";
import type { ExportableMessage } from "@/lib/chat-export";
import type { StreamEvent } from "@/features/chat/model/protocol";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import { docIconFor, formatBytes, isSvgFilename } from "@/lib/doc-attachments";
import {
  InlineFileCard,
  InlineFileCardProvider,
  mergeGeneratedFiles,
  unlinkedGeneratedFiles,
} from "@/components/common/InlineFileCard";
import {
  isRetractionMarker,
  recomputeAnswerContent,
  shouldAppendEventContent,
} from "@/lib/stream";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { AssistantActivity } from "@/features/chat/trace";
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
  activityId?: string;
  channel?: string;
  attachments?: PartnerMessageAttachment[];
  /** Full turn event stream (live turns only; restored history has none). */
  events?: StreamEvent[];
  error?: boolean;
  optimisticId?: number;
}

interface ExternalDraft {
  activityId: string;
  channel?: string;
  events: StreamEvent[];
  content: string;
}

interface PartnerMessageAttachment {
  type: string;
  filename: string;
  mimeType?: string;
  size?: number;
  previewUrl?: string;
  url?: string;
  generated?: boolean;
  origin?: "workspace";
  workspaceId?: string;
  workspaceItemId?: string;
  relativePath?: string;
  sha256?: string;
  title?: string;
  caption?: string;
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
        size:
          typeof obj.size_bytes === "number"
            ? obj.size_bytes
            : typeof sizeRaw === "number"
              ? sizeRaw
              : undefined,
        url: typeof obj.url === "string" ? obj.url : undefined,
        generated: Boolean(obj.generated),
        origin: obj.origin === "workspace" ? "workspace" : undefined,
        workspaceId:
          typeof obj.workspace_id === "string" ? obj.workspace_id : undefined,
        workspaceItemId:
          typeof obj.workspace_item_id === "string"
            ? obj.workspace_item_id
            : undefined,
        relativePath:
          typeof obj.relative_path === "string" ? obj.relative_path : undefined,
        sha256: typeof obj.sha256 === "string" ? obj.sha256 : undefined,
        title: typeof obj.title === "string" ? obj.title : undefined,
        caption: typeof obj.caption === "string" ? obj.caption : undefined,
      };
    })
    .filter((item): item is PartnerMessageAttachment => item !== null);
}

function workspaceAttachments(
  attachments?: PartnerMessageAttachment[],
): MessageAttachment[] {
  return (attachments ?? []).map((attachment) => ({
    type: attachment.type,
    filename: attachment.filename,
    url: attachment.url,
    mime_type: attachment.mimeType,
    generated: attachment.generated,
    size_bytes: attachment.size,
    origin: attachment.origin,
    workspace_id: attachment.workspaceId,
    workspace_item_id: attachment.workspaceItemId,
    relative_path: attachment.relativePath,
    sha256: attachment.sha256,
    title: attachment.title,
    caption: attachment.caption,
  }));
}

function PartnerGeneratedFiles({
  attachments,
  events,
  content,
}: {
  attachments?: PartnerMessageAttachment[];
  events?: StreamEvent[];
  content: string;
}) {
  const files = mergeGeneratedFiles(workspaceAttachments(attachments), events);
  const unlinked = unlinkedGeneratedFiles(content, files);
  if (!unlinked.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {unlinked.map((file) => (
        <InlineFileCard
          key={file.url || file.relative_path || file.filename}
          name={
            file.origin === "workspace"
              ? file.relative_path || ""
              : file.filename || ""
          }
        />
      ))}
    </div>
  );
}

function normalizeHistoryMessages(history: PartnerHistoryMessage[]): ChatMsg[] {
  return history
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      role: message.role as "user" | "assistant",
      content: message.content,
      activityId:
        typeof message.metadata?.activity_id === "string"
          ? message.metadata.activity_id
          : undefined,
      channel: message.channel,
      attachments: normalizeHistoryAttachments(message.attachments),
      events: normalizeHistoryEvents(message.events),
    }));
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
  sessionKey,
  onSessionKeyChange,
  onToast,
  onMessagesChange,
  onRuntimeReady,
  onBusyChange,
  switchingSession = false,
  sharedAcrossBrowsers = false,
  onSelectionStale,
  embedded = false,
}: {
  partnerId: string;
  partnerName: string;
  emoji?: string;
  color?: string;
  avatar?: string;
  /** The active web session key (canonical id), owned by the page so the
   *  Archive tab can switch which conversation the Chat tab is on. */
  sessionKey: string;
  /** Rotate to a different session (new / branch / resume / delete-current). */
  onSessionKeyChange?: (key: string, alreadySaved?: boolean) => void | Promise<void>;
  /** Keep an embedded consultation on its bound conversation. */
  embedded?: boolean;
  onToast?: (message: string) => void;
  /** Lifts the settled conversation up so the page header can export it.
   *  Fires only on discrete message events (send / turn done / clear), not
   *  per streamed token — the live `draft` is intentionally excluded. */
  onMessagesChange?: (messages: ExportableMessage[]) => void;
  /** The socket sends ready only after the on-demand partner runtime exists. */
  onRuntimeReady?: () => void;
  /** Let the owning page defer cross-browser selection changes during a turn. */
  onBusyChange?: (busy: boolean) => void;
  switchingSession?: boolean;
  sharedAcrossBrowsers?: boolean;
  onSelectionStale?: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [olderBefore, setOlderBefore] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [historyLoadedKey, setHistoryLoadedKey] = useState("");
  const [historyLoadError, setHistoryLoadError] = useState(false);
  const [historyRetry, setHistoryRetry] = useState(0);
  const [reconciling, setReconciling] = useState(false);
  const [commandBusy, setCommandBusy] = useState(false);
  const commandBusyRef = useRef(false);
  const [restoreDraft, setRestoreDraft] = useState<{
    id: number;
    content: string;
    attachments: PartnerPendingAttachment[];
  } | null>(null);
  const nextSendIdRef = useRef(0);
  const pendingSendRef = useRef<{
    id: number;
    content: string;
    attachments: PartnerPendingAttachment[];
    visibleContent: string;
    baselineTotal: number;
  } | null>(null);
  const orphanPendingRef = useRef(false);
  const acceptedRef = useRef(false);
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef(streaming);
  streamingRef.current = streaming;
  const [connected, setConnected] = useState(false);
  // Live turn snapshot for rendering. The authoritative accumulator is a
  // local variable inside the socket effect (event handlers may mutate it
  // freely); every frame publishes a fresh snapshot object here.
  const [draft, setDraft] = useState<{
    events: StreamEvent[];
    content: string;
  } | null>(null);
  const [externalDrafts, setExternalDrafts] = useState<ExternalDraft[]>([]);
  const connectionRef = useRef<ReconnectingWebSocket | null>(null);
  // Mirror the active session into a ref so the socket's onopen (which closes
  // over the effect's first render) attaches to the CURRENT session.
  const sessionKeyRef = useRef(sessionKey);
  sessionKeyRef.current = sessionKey;
  const loadedTotalRef = useRef(0);
  const oldestIndexRef = useRef(0);
  const refreshInFlightRef = useRef(false);
  const downloadGeneratedAttachment = useCallback(
    (attachment: MessageAttachment) => {
      if (!attachment.url) return;
      const link = document.createElement("a");
      link.href = attachment.url;
      link.download = attachment.filename || "download";
      document.body.appendChild(link);
      link.click();
      link.remove();
    },
    [],
  );
  useEffect(() => onBusyChange?.(streaming), [onBusyChange, streaming]);
  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);
  // Attach to an in-flight turn only AFTER history has loaded, so the replay's
  // echoed question + answer aren't clobbered by the history replace. Attach
  // once per socket connection.
  const historyReadyRef = useRef(false);
  const attachedRef = useRef(false);
  const lastMessage = messages[messages.length - 1];
  const {
    containerRef: scrollRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll,
  } = useChatAutoScroll({
    hasMessages:
      messages.length > 0 || draft !== null || externalDrafts.length > 0,
    isStreaming: streaming || externalDrafts.length > 0,
    // PartnerComposer sits outside the scrollport and currently exposes no
    // measured-height callback. Sending explicitly re-arms the shared hook
    // below, while streamed content changes drive its normal pin logic.
    composerHeight: 0,
    messageCount: messages.length + (draft ? 1 : 0) + externalDrafts.length,
    lastMessageContent:
      externalDrafts.at(-1)?.content ?? draft?.content ?? lastMessage?.content,
    lastEventCount:
      externalDrafts.at(-1)?.events.length ??
      draft?.events.length ??
      lastMessage?.events?.length,
  });

  const tryAttach = useCallback(() => {
    if (attachedRef.current) return;
    if (!historyReadyRef.current || !sessionKeyRef.current) return;
    const connection = connectionRef.current;
    if (!connection?.connected) return;
    attachedRef.current = true;
    if (
      !connection.send(
        JSON.stringify({
          action: "attach",
          include_activity: !embedded,
          session_key: sessionKeyRef.current,
        }),
      )
    ) {
      attachedRef.current = false;
    }
  }, [embedded]);

  // Restore exactly the active conversation. External-channel activity still
  // arrives live over the activity feed, but must not leak into a resumed or
  // archived web session after refresh.
  useEffect(() => {
    if (!sessionKey) return;
    let cancelled = false;
    historyReadyRef.current = false;
    attachedRef.current = false;
    acceptedRef.current = false;
    loadedTotalRef.current = 0;
    oldestIndexRef.current = 0;
    setMessages([]);
    setOlderBefore(null);
    setLoadingOlder(false);
    setHistoryLoadedKey("");
    setHistoryLoadError(false);
    void getPartnerHistoryPage(partnerId, sessionKey, { limit: 60 })
      .then((page) => {
        if (cancelled) return;
        shouldAutoScrollRef.current = true;
        setMessages(normalizeHistoryMessages(page.messages));
        setOlderBefore(page.next_before);
        loadedTotalRef.current = page.total;
        oldestIndexRef.current = page.start;
        setHistoryLoadedKey(sessionKey);
        historyReadyRef.current = true;
        tryAttach();
        requestAnimationFrame(() => scrollToBottom("instant"));
      })
      .catch(() => {
        if (cancelled) return;
        setHistoryLoadError(true);
        historyReadyRef.current = true;
        tryAttach();
      });
    return () => {
      cancelled = true;
    };
  }, [partnerId, sessionKey, historyRetry, scrollToBottom, shouldAutoScrollRef, tryAttach]);

  const loadOlder = useCallback(async () => {
    if (olderBefore === null || loadingOlder) return;
    const key = sessionKey;
    const container = scrollRef.current;
    const previousHeight = container?.scrollHeight ?? 0;
    const previousTop = container?.scrollTop ?? 0;
    shouldAutoScrollRef.current = false;
    setLoadingOlder(true);
    try {
      const page = await getPartnerHistoryPage(partnerId, key, {
        before: olderBefore,
        limit: 60,
      });
      if (sessionKeyRef.current !== key) return;
      setMessages((current) => [...normalizeHistoryMessages(page.messages), ...current]);
      setOlderBefore(page.next_before);
      oldestIndexRef.current = page.start;
      requestAnimationFrame(() => {
        if (sessionKeyRef.current !== key || !container) return;
        container.scrollTop = previousTop + container.scrollHeight - previousHeight;
      });
    } catch (error) {
      onToast?.(error instanceof Error ? error.message : t("Load failed"));
    } finally {
      if (sessionKeyRef.current === key) setLoadingOlder(false);
    }
  }, [olderBefore, loadingOlder, sessionKey, scrollRef, shouldAutoScrollRef, partnerId, onToast, t]);

  const refreshSharedHistory = useCallback(async () => {
    if (
      !sharedAcrossBrowsers ||
      streaming ||
      draft ||
      externalDrafts.length > 0 ||
      document.visibilityState !== "visible" ||
      !historyReadyRef.current ||
      historyLoadedKey !== sessionKey ||
      refreshInFlightRef.current
    ) return;
    refreshInFlightRef.current = true;
    const key = sessionKeyRef.current;
    try {
      const latest = await getPartnerHistoryPage(partnerId, key, { limit: 60 });
      if (
        sessionKeyRef.current !== key ||
        streamingRef.current ||
        pendingSendRef.current ||
        latest.total === loadedTotalRef.current
      ) return;
      const chunks = [latest.messages];
      let before = latest.next_before;
      let firstIndex = latest.start;
      // Preserve already loaded older history while refreshing the newest
      // segment. Each request remains bounded even for long conversations.
      while (before !== null && before > oldestIndexRef.current) {
        const older = await getPartnerHistoryPage(partnerId, key, {
          before,
          limit: 60,
        });
        if (sessionKeyRef.current !== key || streamingRef.current || pendingSendRef.current) return;
        chunks.unshift(older.messages);
        before = older.next_before;
        firstIndex = older.start;
      }
      if (sessionKeyRef.current !== key || streamingRef.current || pendingSendRef.current) return;
      setMessages((current) =>
        streamingRef.current || pendingSendRef.current
          ? current
          : [
              ...normalizeHistoryMessages(chunks.flat()),
              ...current.filter((message) => message.error),
            ],
      );
      setOlderBefore(before);
      loadedTotalRef.current = latest.total;
      oldestIndexRef.current = firstIndex;
    } catch {
      // Keep the visible transcript and retry on the next idle poll.
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [sharedAcrossBrowsers, streaming, draft, externalDrafts.length, historyLoadedKey, sessionKey, partnerId]);

  useEffect(() => {
    if (!sharedAcrossBrowsers) return;
    const refresh = () => void refreshSharedHistory();
    const timer = window.setInterval(refresh, 15_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [sharedAcrossBrowsers, refreshSharedHistory]);

  useEffect(() => {
    attachedRef.current = false;
    // Authoritative live-turn accumulator. Lives in the effect scope so
    // connection handlers can mutate it cheaply; renders see snapshots only.
    let live: { events: StreamEvent[]; content: string } | null = null;
    const externalLive = new Map<string, ExternalDraft>();
    const publishExternal = () => {
      setExternalDrafts(
        Array.from(externalLive.values(), (item) => ({
          ...item,
          events: [...item.events],
        })),
      );
    };
    // Local providers can emit many tokens between animation frames. Publish
    // one immutable snapshot per frame so React never enters an update storm.
    const {
      publish,
      publishNow,
      cancel: cancelPendingPublish,
    } = createPartnerDraftPublisher(() => live, setDraft);

    const handleMessage = (message: MessageEvent) => {
      let data: {
        type: string;
        content?: string;
        session_key?: string;
        event?: StreamEvent;
        activity_id?: string;
        channel?: string;
        external?: boolean;
      };
      try {
        data = JSON.parse(String(message.data));
      } catch {
        return;
      }
      if (data.type === "ready") {
        setConnected(true);
        onRuntimeReady?.();
        tryAttach();
        return;
      }
      if (data.external && data.activity_id) {
        const activityId = data.activity_id;
        if (data.type === "user_echo") {
          externalLive.set(activityId, {
            activityId,
            channel: data.channel,
            events: [],
            content: "",
          });
          setMessages((msgs) =>
            msgs.some(
              (msg) => msg.activityId === activityId && msg.role === "user",
            )
              ? msgs
              : [
                  ...msgs,
                  {
                    role: "user",
                    content: data.content ?? "",
                    activityId,
                    channel: data.channel,
                  },
                ],
          );
          publishExternal();
        } else if (data.type === "stream_event" && data.event) {
          const current = externalLive.get(activityId) ?? {
            activityId,
            channel: data.channel,
            events: [],
            content: "",
          };
          current.events.push(data.event);
          if (shouldAppendEventContent(data.event)) {
            current.content += data.event.content;
          } else if (isRetractionMarker(data.event)) {
            current.content = recomputeAnswerContent(current.events);
          }
          externalLive.set(activityId, current);
          publishExternal();
        } else if (data.type === "content") {
          const finished = externalLive.get(activityId);
          externalLive.delete(activityId);
          setMessages((msgs) =>
            msgs.some(
              (msg) =>
                msg.activityId === activityId && msg.role === "assistant",
            )
              ? msgs
              : [
                  ...msgs,
                  {
                    role: "assistant",
                    content: data.content || finished?.content || "",
                    activityId,
                    channel: data.channel,
                    events: finished?.events.length
                      ? finished.events
                      : undefined,
                  },
                ],
          );
          publishExternal();
        } else if (data.type === "done" || data.type === "stopped") {
          externalLive.delete(activityId);
          publishExternal();
        }
        return;
      }
      if (data.type === "resuming") {
        // Server is about to replay an in-flight turn (after a refresh).
        orphanPendingRef.current = false;
        acceptedRef.current = true;
        setReconciling(false);
        live = { events: [], content: "" };
        setStreaming(true);
        publish();
        return;
      }
      if (data.type === "turn_busy" || data.type === "stale_session") {
        const rejected = pendingSendRef.current;
        pendingSendRef.current = null;
        acceptedRef.current = false;
        if (rejected) {
          setMessages((current) =>
            current.filter((message) => message.optimisticId !== rejected.id),
          );
          setRestoreDraft(rejected);
        }
        live = null;
        setDraft(null);
        setStreaming(false);
        setReconciling(false);
        if (data.type === "stale_session") {
          void onSelectionStale?.();
          onToast?.(t("Conversation changed in another browser. Please retry."));
        } else {
          onToast?.(t("This conversation is already replying. Please wait."));
        }
        return;
      }
      if (data.type === "accepted") {
        acceptedRef.current = true;
        return;
      }
      if (data.type === "attach_busy" && data.session_key === sessionKeyRef.current) {
        if (orphanPendingRef.current) {
          window.setTimeout(() => {
            if (!orphanPendingRef.current || sessionKeyRef.current !== data.session_key) return;
            attachedRef.current = false;
            tryAttach();
          }, 2_000);
        }
        return;
      }
      if (data.type === "attach_idle" && data.session_key === sessionKeyRef.current) {
        if (!orphanPendingRef.current) return;
        const key = data.session_key;
        const pending = pendingSendRef.current;
        void getPartnerHistoryPage(partnerId, key, { limit: 60 })
          .then((page) => {
            if (sessionKeyRef.current !== key || !orphanPendingRef.current) return;
            const persisted = pending && page.messages.some((item, index) =>
              page.start + index >= pending.baselineTotal &&
              item.role === "user" && item.content === pending.visibleContent,
            );
            setMessages(normalizeHistoryMessages(page.messages));
            setOlderBefore(page.next_before);
            loadedTotalRef.current = page.total;
            oldestIndexRef.current = page.start;
            pendingSendRef.current = null;
            acceptedRef.current = false;
            orphanPendingRef.current = false;
            setStreaming(false);
            setDraft(null);
            setReconciling(false);
            if (pending && !persisted) setRestoreDraft(pending);
          })
          .catch(() => {
            if (sessionKeyRef.current !== key) return;
            window.setTimeout(() => {
              if (!orphanPendingRef.current || sessionKeyRef.current !== key) return;
              attachedRef.current = false;
              tryAttach();
            }, 2_000);
          });
        return;
      }
      if (data.type === "user_echo") {
        // Reconnects replay the active question. Keep the optimistic row that
        // is already present in this mounted page instead of duplicating it.
        const content = data.content ?? "";
        setMessages((msgs) => {
          const last = msgs[msgs.length - 1];
          return last?.role === "user" && last.content === content
            ? msgs
            : [...msgs, { role: "user", content }];
        });
        return;
      }
      if (data.type === "stream_event" && data.event) {
        const event = data.event;
        live ??= { events: [], content: "" };
        live.events.push(event);
        if (shouldAppendEventContent(event)) {
          live.content += event.content;
        } else if (isRetractionMarker(event)) {
          // A capability took this round's text back out of the answer.
          // Same retraction rule as product chat.
          live.content = recomputeAnswerContent(live.events);
        }
        publish();
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
        publishNow();
      } else if (data.type === "done") {
        pendingSendRef.current = null;
        acceptedRef.current = false;
        orphanPendingRef.current = false;
        setReconciling(false);
        setStreaming(false);
        live = null;
        publishNow();
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
        pendingSendRef.current = null;
        acceptedRef.current = false;
        orphanPendingRef.current = false;
        setReconciling(false);
        setStreaming(false);
        publishNow();
      } else if (data.type === "proactive") {
        setMessages((msgs) => [
          ...msgs,
          { role: "assistant", content: data.content ?? "" },
        ]);
      } else if (data.type === "error") {
        const rejected = !acceptedRef.current ? pendingSendRef.current : null;
        if (rejected) {
          pendingSendRef.current = null;
          setMessages((current) =>
            current.filter((item) => item.optimisticId !== rejected.id),
          );
          setRestoreDraft(rejected);
          onToast?.(data.content ?? t("Action failed"));
        } else {
          setMessages((msgs) => [
            ...msgs,
            { role: "assistant", content: data.content ?? "Error", error: true },
          ]);
        }
        live = null;
        publishNow();
        setStreaming(false);
      }
    };

    const connection = new ReconnectingWebSocket(
      wsUrl(`/ws/partners/${partnerId}`),
      {
        onOpen: () => {
          // TCP/WebSocket open is not application readiness: the backend may
          // still be lazily starting this partner. The explicit ready frame
          // below is what enables the composer.
          setConnected(false);
          attachedRef.current = false;
        },
        onMessage: handleMessage,
        onDisconnect: () => {
          setConnected(false);
          orphanPendingRef.current = Boolean(pendingSendRef.current || streamingRef.current);
          if (orphanPendingRef.current) setReconciling(true);
          setStreaming(false);
          externalLive.clear();
          setExternalDrafts([]);
        },
      },
      {
        shouldReconnect: () =>
          document.visibilityState === "visible" && navigator.onLine !== false,
      },
    );
    connectionRef.current = connection;

    const wakeWhenActive = () => {
      if (
        document.visibilityState === "visible" &&
        navigator.onLine !== false
      ) {
        connection.wake();
      }
    };
    window.addEventListener("focus", wakeWhenActive);
    window.addEventListener("online", wakeWhenActive);
    document.addEventListener("visibilitychange", wakeWhenActive);
    connection.start();

    return () => {
      cancelPendingPublish();
      externalLive.clear();
      setExternalDrafts([]);
      window.removeEventListener("focus", wakeWhenActive);
      window.removeEventListener("online", wakeWhenActive);
      document.removeEventListener("visibilitychange", wakeWhenActive);
      connection.stop();
      if (connectionRef.current === connection) connectionRef.current = null;
    };
  }, [onRuntimeReady, onSelectionStale, onToast, partnerId, t, tryAttach]);

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
    connectionRef.current?.send(
      JSON.stringify({ action: "stop", session_key: sessionKey }),
    );
  }, [sessionKey]);

  // Escape interrupts a streaming answer. Bound on `window` rather than the
  // chat container because the composer is disabled mid-stream, so focus
  // usually sits on <body> and a scoped listener would never see the key.
  // An open overlay owns Escape first — Modal, PickerShell, ConfirmDialog and
  // the preview drawers all close on it — so bail while one is mounted
  // instead of killing the turn behind a dismissal the user meant for the
  // dialog. Every overlay marks itself with a dialog role and unmounts when
  // closed, which makes the DOM the single source of truth here.
  useEffect(() => {
    if (!streaming) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) {
        return;
      }
      sendStop();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [streaming, sendStop]);

  // Session-management commands run client-side: they switch the active
  // session or stop the turn — things a server text reply can't do. Returns
  // true when handled (so the caller skips the normal send).
  const runClientCommand = useCallback(
    async (command: string, arg: string): Promise<void> => {
      if (!onSessionKeyChange && command !== "/stop") {
        onToast?.(t("Manage partner conversations on the partner page."));
        return;
      }
      switch (command) {
        case "/new":
        case "/clear": {
          const next = freshPartnerSessionKey();
          if (messages.length === 0) {
            await onSessionKeyChange?.(next);
            break;
          }
          try {
            const result = await archivePartnerSession(partnerId, sessionKey);
            setMessages([]);
            if (sharedAcrossBrowsers) {
              if (result.active_session_key) await onSessionKeyChange?.(result.active_session_key, true);
              else await onSelectionStale?.();
            } else {
              await onSessionKeyChange?.(next);
            }
          } catch (error) {
            onToast?.(error instanceof Error ? error.message : t("Action failed"));
          }
          break;
        }
        case "/branch": {
          const next = freshPartnerSessionKey();
          try {
            const result = await branchPartnerSession(partnerId, sessionKey, next);
            onToast?.(
              t("Branched — the original is archived as {{id}}", {
                id: sessionKey,
              }),
            );
            if (sharedAcrossBrowsers) {
              if (result.active_session_key) await onSessionKeyChange?.(result.active_session_key, true);
              else await onSelectionStale?.();
            } else {
              await onSessionKeyChange?.(next); // history reload picks up the copy
            }
          } catch (error) {
            onToast?.(error instanceof Error ? error.message : t("Nothing to branch yet."));
          }
          break;
        }
        case "/resume": {
          if (!arg) {
            onToast?.(t("Usage: /resume <session ID>"));
            break;
          }
          try {
            const result = await resumePartnerSession(partnerId, arg);
            if (sharedAcrossBrowsers) {
              if (result.active_session_key) await onSessionKeyChange?.(result.active_session_key, true);
              else await onSelectionStale?.();
            } else {
              await onSessionKeyChange?.(arg);
            }
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
            const result = await deletePartnerSession(partnerId, arg);
            onToast?.(t("Conversation deleted"));
            if (arg === sessionKey) {
              setMessages([]);
              if (sharedAcrossBrowsers) {
                if (result.active_session_key) await onSessionKeyChange?.(result.active_session_key, true);
                else await onSelectionStale?.();
              } else {
                await onSessionKeyChange?.(freshPartnerSessionKey());
              }
            } else if (sharedAcrossBrowsers && result.active_session_key) {
              await onSessionKeyChange?.(result.active_session_key, true);
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
                  `- \`${s.session_key}\`${s.archived ? ` (${t("Archived")})` : ""} — ${displaySessionTitle(
                    s.title,
                    t("New conversation"),
                  )} · ${s.message_count}`,
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
            scrollToBottom("instant");
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
      messages.length,
      sharedAcrossBrowsers,
      onSessionKeyChange,
      onSelectionStale,
      onToast,
      scrollToBottom,
      sendStop,
      t,
    ],
  );

  const handleSend = useCallback(
    (content: string, attachments: PartnerPendingAttachment[]): boolean | "handled" => {
      if (streaming || reconciling || commandBusyRef.current || !connected || switchingSession || historyLoadedKey !== sessionKey) return false;

      // A new user-authored turn explicitly returns to live-follow mode.
      // During the answer, the shared hook releases that mode as soon as the
      // user scrolls upward and only re-arms near the bottom.
      shouldAutoScrollRef.current = true;
      const command =
        attachments.length === 0 ? parseClientCommand(content) : null;
      if (command) {
        if (command.command !== "/sessions" && command.command !== "/stop") {
          commandBusyRef.current = true;
          setCommandBusy(true);
        }
        void runClientCommand(command.command, command.arg).finally(() => {
          commandBusyRef.current = false;
          setCommandBusy(false);
        });
        return "handled";
      }

      const visibleContent =
        content ||
        (attachments.every((item) => item.type === "image")
          ? t("Please analyze the attached image(s).")
          : t("Please use the attached file(s)."));
      const sent = connectionRef.current?.send(
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
      if (!sent) return false;
      const optimisticId = ++nextSendIdRef.current;
      acceptedRef.current = false;
      pendingSendRef.current = {
        id: optimisticId,
        content,
        attachments: [...attachments],
        visibleContent,
        baselineTotal: loadedTotalRef.current,
      };
      setMessages((msgs) => [
        ...msgs,
        {
          role: "user",
          content: visibleContent,
          attachments: sentAttachmentsForMessage(attachments),
          optimisticId,
        },
      ]);
      setDraft({ events: [], content: "" });
      setStreaming(true);
      scrollToBottom("instant");
      return true;
    },
    [
      sessionKey,
      connected,
      streaming,
      reconciling,
      switchingSession,
      historyLoadedKey,
      scrollToBottom,
      runClientCommand,
      shouldAutoScrollRef,
      t,
    ],
  );

  return (
    <div className={`flex h-full min-h-0 flex-col ${embedded ? "px-4" : ""}`}>
      <div
        ref={scrollRef}
        data-chat-scroll-root="true"
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto px-1 py-4"
      >
        {historyLoadError ? (
          <div className="flex items-center justify-center gap-2 py-2 text-[12px] text-[var(--muted-foreground)]">
            {t("Load failed")}
            <button
              type="button"
              onClick={() => setHistoryRetry((value) => value + 1)}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[var(--foreground)]"
            >
              {t("Retry")}
            </button>
          </div>
        ) : null}
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
                {t(
                  "Say hello — channels are optional, and any connected channel shares this partner's memory.",
                )}
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-5">
            {olderBefore !== null ? (
              <button
                type="button"
                onClick={() => void loadOlder()}
                disabled={loadingOlder}
                className="self-center rounded-md border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
              >
                {loadingOlder ? t("Loading...") : t("Load older messages")}
              </button>
            ) : null}
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
                      <InlineFileCardProvider
                        attachments={workspaceAttachments(msg.attachments)}
                        events={msg.events}
                        onOpen={downloadGeneratedAttachment}
                      >
                        <AssistantResponse content={msg.content} />
                        <PartnerGeneratedFiles
                          attachments={msg.attachments}
                          events={msg.events}
                          content={msg.content}
                        />
                      </InlineFileCardProvider>
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
                    <InlineFileCardProvider
                      attachments={[]}
                      events={draft.events}
                      onOpen={downloadGeneratedAttachment}
                    >
                      <AssistantResponse content={draft.content} />
                      <PartnerGeneratedFiles
                        events={draft.events}
                        content={draft.content}
                      />
                    </InlineFileCardProvider>
                  ) : null}
                </div>
              </div>
            )}

            {externalDrafts.map((externalDraft) => (
              <div
                key={externalDraft.activityId}
                className="flex items-start gap-2.5"
              >
                <PartnerAvatar
                  name={partnerName}
                  emoji={emoji}
                  color={color}
                  size={26}
                />
                <div className="min-w-0 flex-1">
                  <AssistantActivity
                    events={externalDraft.events}
                    isStreaming
                    content={externalDraft.content}
                    className="mb-1.5"
                    agentName={partnerName}
                    showMark={false}
                    headerClassName="min-h-[26px]"
                  />
                  {externalDraft.content ? (
                    <InlineFileCardProvider
                      attachments={[]}
                      events={externalDraft.events}
                      onOpen={downloadGeneratedAttachment}
                    >
                      <AssistantResponse content={externalDraft.content} />
                      <PartnerGeneratedFiles
                        events={externalDraft.events}
                        content={externalDraft.content}
                      />
                    </InlineFileCardProvider>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-2xl px-1 pb-4">
        {!connected ? (
          <p className="mb-1 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Connecting…")}
          </p>
        ) : null}
        <PartnerComposer
          onSend={handleSend}
          onStop={sendStop}
          streaming={streaming}
          disabled={!connected || reconciling || commandBusy || switchingSession || historyLoadedKey !== sessionKey}
          restoreDraft={restoreDraft ?? undefined}
        />
      </div>
    </div>
  );
}
