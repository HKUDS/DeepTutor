"use client";

import { useEffect, useRef, useState } from "react";
import { Send, Loader2, MessageSquare, X } from "lucide-react";
import { wsUrl } from "@/lib/api";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Page, Book } from "@/lib/book-types";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export interface BookChatPanelProps {
  book: Book | null;
  page: Page | null;
  open: boolean;
  onClose: () => void;
}

export default function BookChatPanel({
  book,
  page,
  open,
  onClose,
}: BookChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    return () => {
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  useEffect(() => {
    sessionIdRef.current = null;
    setMessages([]);
  }, [book?.id]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages]);

  function ensureSocket(): WebSocket {
    const existing = socketRef.current;
    if (existing && existing.readyState === WebSocket.OPEN) {
      return existing;
    }
    if (existing && existing.readyState === WebSocket.CONNECTING) {
      return existing;
    }
    const ws = new WebSocket(wsUrl("/api/v1/chat"));
    socketRef.current = ws;
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case "session":
            sessionIdRef.current = data.session_id;
            break;
          case "stream":
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant" && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  content: last.content + String(data.content || ""),
                };
              } else {
                next.push({
                  role: "assistant",
                  content: String(data.content || ""),
                  streaming: true,
                });
              }
              return next;
            });
            break;
          case "result":
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                next[next.length - 1] = {
                  ...last,
                  content: data.content || last.content,
                  streaming: false,
                };
              } else {
                next.push({
                  role: "assistant",
                  content: String(data.content || ""),
                });
              }
              return next;
            });
            setBusy(false);
            break;
          case "error":
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: `❌ ${data.message || "error"}` },
            ]);
            setBusy(false);
            break;
          default:
            break;
        }
      } catch {
        // ignore
      }
    };
    ws.onclose = () => {
      socketRef.current = null;
      setBusy(false);
    };
    ws.onerror = () => setBusy(false);
    return ws;
  }

  function buildContextPreface(): string {
    const lines: string[] = [];
    if (book?.title) lines.push(`Book: ${book.title}`);
    if (page?.title) lines.push(`Current page: ${page.title}`);
    if (page?.learning_objectives?.length) {
      lines.push(`Objectives: ${page.learning_objectives.join("; ")}`);
    }
    return lines.join("\n");
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    const ws = ensureSocket();
    const payload = {
      message: text,
      session_id: sessionIdRef.current,
      kb_name: book?.knowledge_bases?.[0] || "",
      enable_rag: !!(book?.knowledge_bases && book.knowledge_bases.length > 0),
      enable_web_search: false,
      context: buildContextPreface(),
    };
    const dispatch = () => ws.send(JSON.stringify(payload));
    if (ws.readyState === WebSocket.OPEN) {
      dispatch();
    } else {
      ws.addEventListener("open", dispatch, { once: true });
    }
  }

  if (!open) return null;

  return (
    <aside className="fixed inset-x-0 top-0 z-[75] flex h-[calc(100dvh_-_72px_-_env(safe-area-inset-bottom))] w-full flex-col border-l border-[var(--border)] bg-[var(--card)]/95 shadow-2xl backdrop-blur md:static md:h-full md:w-[360px] md:shrink-0 md:bg-[var(--card)]/40 md:shadow-none">
      <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <MessageSquare className="h-4 w-4 text-[var(--primary)]" />
          Page Chat
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div ref={scrollerRef} className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 ? (
          <div className="text-xs text-[var(--muted-foreground)]">
            Ask a question about this page. Context (book + chapter) is sent
            automatically.
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? "ml-6 rounded-2xl rounded-tr-sm bg-[var(--primary)]/10 px-3 py-2 text-sm text-[var(--foreground)]"
                    : "mr-6 rounded-2xl rounded-tl-sm bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)]"
                }
              >
                {m.role === "assistant" ? (
                  <MarkdownRenderer content={m.content} variant="compact" />
                ) : (
                  m.content
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="border-t border-[var(--border)] p-3"
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this page…"
            rows={2}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            className="flex-1 resize-none rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-[16px] text-[var(--foreground)] focus:border-[var(--primary)] focus:outline-none sm:text-sm"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="inline-flex h-9 items-center justify-center rounded-md bg-[var(--primary)] px-3 text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
      </form>
    </aside>
  );
}
