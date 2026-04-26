"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  Download,
  Loader2,
  Send,
} from "lucide-react";
import { apiUrl, wsUrl } from "@/lib/api";
import { firstParam } from "@/lib/route-params";
import AssistantResponse from "@/components/common/AssistantResponse";
import { SimpleComposerInput } from "@/components/chat/home/SimpleComposerInput";
import { downloadChatMarkdown } from "@/lib/chat-export";
import type { MessageItem } from "@/context/UnifiedChatContext";
import type {
  NotebookSaveMessage,
  NotebookSavePayload,
} from "@/components/notebook/SaveToNotebookModal";

const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  { ssr: false },
);

interface BotInfo {
  bot_id: string;
  name: string;
  running: boolean;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  thinking?: string[];
}

export default function BotChatPage() {
  const params = useParams<{ botId?: string | string[] }>();
  const botId = firstParam(params?.botId);
  const router = useRouter();
  const { t } = useTranslation();

  const [bot, setBot] = useState<BotInfo | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const thinkingRef = useRef<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const [showSaveModal, setShowSaveModal] = useState(false);

  const exportTitle = useMemo(() => {
    const firstUser = messages
      .find((m) => m.role === "user")
      ?.content.trim()
      .slice(0, 80);
    return firstUser || bot?.name || botId || "Bot Chat";
  }, [bot?.name, botId, messages]);

  const exportMessages = useMemo<MessageItem[]>(
    () =>
      messages.map((m) => ({
        role: m.role,
        content: m.content,
      })),
    [messages],
  );

  const notebookSaveMessages = useMemo<NotebookSaveMessage[]>(
    () =>
      messages.map((m) => ({
        role: m.role,
        content: m.content,
      })),
    [messages],
  );

  const notebookSavePayload = useMemo<NotebookSavePayload | null>(() => {
    if (!messages.length) return null;
    return {
      recordType: "tutorbot",
      title: exportTitle,
      // SaveToNotebookModal rebuilds userQuery / output from the user's
      // selected message subset; we just need a non-null payload here.
      userQuery: "",
      output: "",
      metadata: {
        source: "agent_chat",
        bot_id: botId ?? null,
        bot_name: bot?.name ?? null,
        total_message_count: messages.length,
      },
    };
  }, [bot?.name, botId, exportTitle, messages.length]);

  const handleDownloadMarkdown = useCallback(() => {
    if (!exportMessages.length) return;
    downloadChatMarkdown(exportMessages, { title: exportTitle });
  }, [exportMessages, exportTitle]);

  const handleCloseSaveModal = useCallback(() => setShowSaveModal(false), []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior,
      });
    });
  }, []);

  useEffect(() => {
    if (!botId) {
      return;
    }
    fetch(apiUrl(`/api/v1/tutorbot/${botId}`))
      .then((r) => (r.ok ? r.json() : null))
      .then(setBot)
      .catch(() => setBot(null));

    fetch(apiUrl(`/api/v1/tutorbot/${botId}/history`))
      .then((r) => (r.ok ? r.json() : []))
      .then((history: { role: string; content: string }[]) => {
        const restored: ChatMsg[] = history
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
          }));
        if (restored.length) {
          setMessages(restored);
          // Markdown/KaTeX inside AssistantResponse can grow the container after
          // the first paint — re-snap a few times so we land at the bottom.
          requestAnimationFrame(() => scrollToBottom("instant"));
          window.setTimeout(() => scrollToBottom("instant"), 80);
          window.setTimeout(() => scrollToBottom("instant"), 250);
        }
      })
      .catch(() => {});
  }, [botId, scrollToBottom]);

  useEffect(() => {
    if (!botId) {
      return;
    }
    const ws = new WebSocket(wsUrl(`/api/v1/tutorbot/${botId}/ws`));
    wsRef.current = ws;

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "thinking") {
        thinkingRef.current = [...thinkingRef.current, data.content];
        setThinking(thinkingRef.current);
        scrollToBottom();
      } else if (data.type === "content") {
        const snap = thinkingRef.current;
        setMessages((msgs) => [
          ...msgs,
          {
            role: "assistant",
            content: data.content,
            thinking: snap.length ? [...snap] : undefined,
          },
        ]);
        thinkingRef.current = [];
        setThinking([]);
        scrollToBottom();
      } else if (data.type === "done") {
        setStreaming(false);
        setTimeout(() => inputRef.current?.focus(), 50);
      } else if (data.type === "proactive") {
        setMessages((msgs) => [
          ...msgs,
          { role: "assistant", content: data.content },
        ]);
        scrollToBottom();
      } else if (data.type === "error") {
        setMessages((msgs) => [
          ...msgs,
          { role: "assistant", content: `Error: ${data.content}` },
        ]);
        thinkingRef.current = [];
        setThinking([]);
        setStreaming(false);
      }
    };

    ws.onclose = () => {
      setStreaming(false);
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [botId, scrollToBottom]);

  const handleSend = useCallback(
    (content: string) => {
      if (
        !botId ||
        streaming ||
        !wsRef.current ||
        wsRef.current.readyState !== WebSocket.OPEN
      )
        return;

      setMessages((msgs) => [...msgs, { role: "user", content }]);
      setStreaming(true);
      setThinking([]);
      wsRef.current.send(JSON.stringify({ content }));
      scrollToBottom();
    },
    [botId, streaming, scrollToBottom],
  );

  const handleManualSend = useCallback(() => {
    const content = inputRef.current?.value.trim();
    if (content) {
      handleSend(content);
      if (inputRef.current) inputRef.current.value = "";
    }
  }, [handleSend]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3 sm:gap-3 sm:px-5">
        <button
          onClick={() => router.push("/agents")}
          className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Bot className="h-4 w-4 text-[var(--muted-foreground)]" />
        <span className="min-w-0 truncate text-[14px] font-medium text-[var(--foreground)]">
          {bot?.name ?? botId}
        </span>
        {bot?.running && (
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
          <button
            onClick={() => setShowSaveModal(true)}
            disabled={!notebookSavePayload}
            title={t("Save to Notebook")}
            aria-label={t("Save to Notebook")}
            className="inline-flex h-9 w-9 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)]/50 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)] sm:h-auto sm:w-auto sm:px-3 sm:py-1.5"
          >
            <BookOpen className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{t("Save to Notebook")}</span>
          </button>
          <button
            onClick={handleDownloadMarkdown}
            disabled={!messages.length}
            title={t("Download chat history as Markdown")}
            aria-label={t("Download Markdown")}
            className="inline-flex h-9 w-9 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)]/50 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)] sm:h-auto sm:w-auto sm:px-3 sm:py-1.5"
          >
            <Download className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{t("Download Markdown")}</span>
          </button>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-5 [scrollbar-gutter:stable] sm:px-5 sm:py-6"
      >
        <div className="mx-auto max-w-[720px] space-y-5">
          {messages.length === 0 && !streaming && (
            <div className="flex flex-col items-center justify-center pt-24 text-center">
              <div className="mb-3 rounded-xl bg-[var(--muted)] p-3 text-[var(--muted-foreground)]">
                <Bot size={22} />
              </div>
              <p className="text-[14px] font-medium text-[var(--foreground)]">
                {t("Chat with {{name}}", { name: bot?.name ?? botId })}
              </p>
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                {t("Send a message to start the conversation.")}
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={msg.role === "user" ? "flex justify-end" : ""}
            >
              {msg.role === "user" ? (
                <div className="max-w-[90%] break-words rounded-2xl rounded-br-md bg-[var(--primary)] px-4 py-2.5 text-[14px] text-[var(--primary-foreground)] sm:max-w-[80%]">
                  {msg.content}
                </div>
              ) : (
                <div className="max-w-full">
                  {msg.thinking && msg.thinking.length > 0 && (
                    <details className="mb-2">
                      <summary className="cursor-pointer text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                        {t("Thinking ({{count}} steps)", {
                          count: msg.thinking.length,
                        })}
                      </summary>
                      <div className="mt-1 space-y-1 border-l-2 border-[var(--border)] pl-3">
                        {msg.thinking.map((th, j) => (
                          <p
                            key={j}
                            className="text-[12px] text-[var(--muted-foreground)]"
                          >
                            {th}
                          </p>
                        ))}
                      </div>
                    </details>
                  )}
                  <AssistantResponse content={msg.content} />
                </div>
              )}
            </div>
          ))}

          {/* Streaming indicator */}
          {streaming && (
            <div className="space-y-2">
              {thinking.length > 0 && (
                <div className="space-y-1 border-l-2 border-[var(--border)] pl-3">
                  {thinking.map((th, i) => (
                    <p
                      key={i}
                      className="text-[12px] text-[var(--muted-foreground)]"
                    >
                      {th}
                    </p>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>
                  {thinking.length > 0 ? t("Working...") : t("Thinking...")}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] px-4 py-3 sm:px-5">
        <div className="mx-auto flex max-w-[720px] items-end gap-2">
          <SimpleComposerInput
            textareaRef={inputRef}
            onSend={handleSend}
            disabled={streaming}
          />
          <button
            onClick={handleManualSend}
            disabled={streaming}
            className="flex h-[42px] w-[42px] items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>

      <SaveToNotebookModal
        open={showSaveModal}
        payload={notebookSavePayload}
        messages={notebookSaveMessages}
        onClose={handleCloseSaveModal}
      />
    </div>
  );
}
