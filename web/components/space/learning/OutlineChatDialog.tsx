"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Sparkles, X } from "lucide-react";

import { browserStorage } from "@/shared/storage";
import { shouldAppendEventContent } from "@/lib/stream";
import { getSession } from "@/lib/session-api";
import { resolveMasterySession } from "@/lib/learning-api";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { UnifiedTurnClient } from "@/features/chat/transport/UnifiedTurnClient";
import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import { STUDY_COMPOSER_WIDTH } from "./MasteryComposer";
import AssistantResponse from "@/components/common/AssistantResponse";

interface DialogMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  events?: StreamEvent[];
}

const SESSION_STORAGE_KEY = "dt.mastery.outline.session";

/**
 * A modal that opens the outline conversation for this path.
 *
 * Relies on ``resolveMasterySession`` (which creates / reuses a session
 * bound to the path with mode ``outline``) so the backend always accepts
 * ``start_turn`` commands with ``capability: "mastery_path"`` — a new ad-hoc
 * session without the binding would be rejected by the admission guard.
 *
 * The session id is persisted in browser storage so re-opening the dialog
 * resumes the same conversation across page visits.
 *
 * Visual style mirrors ``MasteryStudy`` — rounded bubbles, markdown
 * rendering, streaming typewriter, same colour tokens.
 */
export function OutlineChatDialog({
  pathId,
  onClose,
}: {
  pathId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<DialogMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const storedSessionIdRef = useRef<string | null>(null);
  const clientRef = useRef<UnifiedTurnClient | null>(null);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(
    new Set(),
  );
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // On mount: resolve the outline session and load its messages.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    void resolveMasterySession(pathId, "outline")
      .then((placed) => {
        if (cancelled) return;
        const sid = placed.session_id;
        setSessionId(sid);
        storedSessionIdRef.current = sid;

        // Also store in local storage so the session is recoverable after
        // a page reload.
        const stored = browserStorage.readRaw("local", SESSION_STORAGE_KEY);
        let storedMap: Record<string, string> = {};
        try {
          storedMap = JSON.parse(stored || "{}");
        } catch {
          /* ignore */
        }
        storedMap[pathId] = sid;
        browserStorage.writeRaw(
          "local",
          SESSION_STORAGE_KEY,
          JSON.stringify(storedMap),
        );

        return getSession(sid);
      })
      .then((session) => {
        if (cancelled || !session) return;
        const restored = (session.messages || [])
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: String(m.content || ""),
            events: m.events || [],
          }));
        setMessages(restored);
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([
            {
              role: "assistant" as const,
              content: t("Could not load the outline conversation."),
            },
          ]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [pathId, t]);

  // Cleanup WebSocket + timers on unmount.
  useEffect(() => {
    const retryTimers = retryTimersRef.current;
    return () => {
      retryTimers.forEach((timer) => clearTimeout(timer));
      retryTimers.clear();
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
  }, []);

  // Pin to bottom when messages change.
  useLayoutEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages]);

  // Focus the dialog on mount.
  useEffect(() => {
    queueMicrotask(() => {
      dialogRef.current?.focus();
    });
  }, [loading]);

  // ---------- WebSocket event handler ----------

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      if (event.type === "session") {
        const meta = (event.metadata || {}) as Record<string, unknown>;
        const sid =
          typeof meta.session_id === "string"
            ? meta.session_id
            : typeof event.session_id === "string"
              ? event.session_id
              : "";
        if (sid) {
          setSessionId(sid);
          storedSessionIdRef.current = sid;
        }
        return;
      }
      if (event.type === "done") {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { ...last, streaming: false };
          }
          return next;
        });
        setBusy(false);
        return;
      }
      if (event.type === "wait_for_input") {
        setBusy(false);
        return;
      }
      if (event.type === "error") {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant" as const,
            content: event.content || t("Error"),
            streaming: false,
          },
        ]);
        setBusy(false);
        return;
      }
      // Append content delta.
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        const delta = shouldAppendEventContent(event)
          ? event.content || ""
          : "";
        if (last && last.role === "assistant" && last.streaming) {
          next[next.length - 1] = {
            ...last,
            content: last.content + delta,
            events: [...(last.events || []), event],
          };
        } else if (delta || event.type !== "content") {
          next.push({
            role: "assistant" as const,
            content: delta,
            streaming: true,
            events: [event],
          });
        }
        return next;
      });
    },
    [],
  );

  // ---------- send ----------

  const ensureClient = useCallback((): UnifiedTurnClient => {
    if (clientRef.current) return clientRef.current;
    const client = new UnifiedTurnClient(
      (event) => handleEvent(event),
      () => setBusy(false),
    );
    clientRef.current = client;
    client.connect();
    return client;
  }, [handleEvent]);

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      const text = submission.content.trim();
      if (!text || busy) return;

      const sid = storedSessionIdRef.current;
      if (!sid) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant" as const,
            content: t("Could not start the outline conversation."),
            streaming: false,
          },
        ]);
        return;
      }

      setMessages((prev) => [...prev, { role: "user" as const, content: text }]);
      setBusy(true);

      const client = ensureClient();
      client.send({
        type: "start_turn",
        content: text,
        session_id: sid,
        capability: "mastery_path",
        mastery_path_id: pathId,
        mastery_session_mode: "outline",
        knowledge_bases: submission.knowledgeBases ?? [],
      });
    },
    [busy, ensureClient, pathId, t],
  );

  const cancelStreaming = useCallback(() => {
    clientRef.current?.disconnect();
    clientRef.current = null;
    setBusy(false);
  }, []);

  function handleDialogKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  // ---------- render ----------

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="outline-chat-title"
      tabIndex={-1}
      onKeyDown={handleDialogKeyDown}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm sm:p-6"
    >
      <div className="flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--card)] px-4 py-3">
          <h2
            id="outline-chat-title"
            className="text-sm font-semibold text-[var(--foreground)]"
          >
            {t("Outline chat")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t("Close")}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Messages */}
        <div
          ref={scrollerRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[var(--background)] px-4 py-4 sm:px-6"
        >
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : messages.length === 0 ? (
            // Empty state — first time the dialog is opened for this path.
            <div className="flex h-full min-h-48 flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--primary)]/10">
                <Sparkles className="h-5 w-5 text-[var(--primary)]" />
              </div>
              <h3 className="text-base font-semibold text-[var(--foreground)]">
                {t("Outline chat")}
              </h3>
              <p className="max-w-sm text-sm leading-6 text-[var(--muted-foreground)]">
                {t(
                  "Describe how you want to change the outline, and the tutor will help you adjust it.",
                )}
              </p>
            </div>
          ) : (
            messages.map((msg, index) => (
              <div key={index} className="mb-3">
                {msg.role === "user" ? (
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl bg-[var(--primary)]/10 px-4 py-2.5 text-sm text-[var(--foreground)]">
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-start">
                    <div className="max-w-[85%] rounded-2xl border border-[var(--border)]/30 bg-[var(--card)] px-4 py-2.5 text-sm leading-7 text-[var(--foreground)]">
                      {msg.content ? (
                        <AssistantResponse
                          content={msg.content}
                          isStreaming={msg.streaming ?? false}
                          events={msg.events}
                        />
                      ) : msg.streaming ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted-foreground)]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted-foreground)] [animation-delay:0.15s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted-foreground)] [animation-delay:0.3s]" />
                        </span>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Composer — same StandaloneComposer as the learning page */}
        <StandaloneComposer
          onSubmit={handleSubmit}
          onCancelStreaming={cancelStreaming}
          isStreaming={busy}
          hasMessages={messages.length > 0}
          showCapabilityChip={false}
          maxWidthClass={STUDY_COMPOSER_WIDTH}
          maxInputHeight={128}
          inputPlaceholder={
            loading
              ? ""
              : t("Describe what to change in the outline\u2026")
          }
        />
      </div>
    </div>
  );
}