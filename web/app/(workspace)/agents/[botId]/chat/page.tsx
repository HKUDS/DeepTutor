"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Bot, Loader2, Send } from "lucide-react";
import { apiUrl, wsUrl } from "@/lib/api";
import AssistantResponse from "@/components/common/AssistantResponse";

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
  const { botId } = useParams<{ botId: string }>();
  const router = useRouter();

  const [bot, setBot] = useState<BotInfo | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const thinkingRef = useRef<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }, []);

  useEffect(() => {
    fetch(apiUrl(`/api/v1/tutorbot/${botId}`))
      .then((r) => (r.ok ? r.json() : null))
      .then(setBot)
      .catch(() => setBot(null));

    fetch(apiUrl(`/api/v1/tutorbot/${botId}/history`))
      .then((r) => (r.ok ? r.json() : []))
      .then((history: { role: string; content: string }[]) => {
        const restored: ChatMsg[] = history
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
        if (restored.length) setMessages(restored);
      })
      .catch(() => {});
  }, [botId]);

  useEffect(() => {
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
          { role: "assistant", content: data.content, thinking: snap.length ? [...snap] : undefined },
        ]);
        thinkingRef.current = [];
        setThinking([]);
        scrollToBottom();
      } else if (data.type === "done") {
        setStreaming(false);
        setTimeout(() => inputRef.current?.focus(), 50);
      } else if (data.type === "proactive") {
        setMessages((msgs) => [...msgs, { role: "assistant", content: data.content }]);
        scrollToBottom();
      } else if (data.type === "error") {
        setMessages((msgs) => [...msgs, { role: "assistant", content: `Error: ${data.content}` }]);
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

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || streaming || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    setMessages((msgs) => [...msgs, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    setThinking([]);
    wsRef.current.send(JSON.stringify({ content: text }));
    scrollToBottom();
  }, [input, streaming, scrollToBottom]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    },
    [send],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-3">
        <button
          onClick={() => router.push("/agents")}
          className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Bot className="h-4 w-4 text-[var(--muted-foreground)]" />
        <span className="text-[14px] font-medium text-[var(--foreground)]">
          {bot?.name ?? botId}
        </span>
        {bot?.running && (
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6 [scrollbar-gutter:stable]">
        <div className="mx-auto max-w-[720px] space-y-5">
          {messages.length === 0 && !streaming && (
            <div className="flex flex-col items-center justify-center pt-24 text-center">
              <div className="mb-3 rounded-xl bg-[var(--muted)] p-3 text-[var(--muted-foreground)]">
                <Bot size={22} />
              </div>
              <p className="text-[14px] font-medium text-[var(--foreground)]">
                Chat with {bot?.name ?? botId}
              </p>
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                Send a message to start the conversation.
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={msg.role === "user" ? "flex justify-end" : ""}>
              {msg.role === "user" ? (
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[var(--primary)] px-4 py-2.5 text-[14px] text-[var(--primary-foreground)]">
                  {msg.content}
                </div>
              ) : (
                <div className="max-w-full">
                  {msg.thinking && msg.thinking.length > 0 && (
                    <details className="mb-2">
                      <summary className="cursor-pointer text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                        Thinking ({msg.thinking.length} steps)
                      </summary>
                      <div className="mt-1 space-y-1 border-l-2 border-[var(--border)] pl-3">
                        {msg.thinking.map((t, j) => (
                          <p key={j} className="text-[12px] text-[var(--muted-foreground)]">{t}</p>
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
                  {thinking.map((t, i) => (
                    <p key={i} className="text-[12px] text-[var(--muted-foreground)]">{t}</p>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>{thinking.length > 0 ? "Working..." : "Thinking..."}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] px-5 py-3">
        <div className="mx-auto flex max-w-[720px] items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            rows={1}
            disabled={streaming}
            className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-transparent px-4 py-2.5 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] disabled:opacity-50 placeholder:text-[var(--muted-foreground)]/40"
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="flex h-[42px] w-[42px] items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
