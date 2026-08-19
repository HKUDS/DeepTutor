"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Users } from "lucide-react";
import DualComposer from "@/components/dual/DualComposer";
import DualMessageList, { type DualMessage } from "@/components/dual/DualMessageList";
import {
  UnifiedWSClient,
  type StartTurnMessage,
  type StreamEvent,
} from "@/lib/unified-ws";

function newMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function looksLikeDualEnded(text: string, stage?: string): boolean {
  if (stage === "debrief") return true;
  const t = (text || "").toLowerCase();
  return (
    t.includes("dual-channel debrief") ||
    t.includes("simulation has ended") ||
    t.includes("房间已结束")
  );
}

export default function DualPage() {
  const [messages, setMessages] = useState<DualMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [closed, setClosed] = useState(false);
  const [dtSessionId, setDtSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [everConnected, setEverConnected] = useState(false);

  const clientRef = useRef<UnifiedWSClient | null>(null);
  const sessionRef = useRef<string | null>(null);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    sessionRef.current = dtSessionId;
  }, [dtSessionId]);

  const handleEvent = useCallback((event: StreamEvent) => {
    if (event.type === "session" || event.type === "session_meta") {
      const metadata = (event.metadata || {}) as Record<string, unknown>;
      const sessionId =
        typeof metadata.session_id === "string"
          ? metadata.session_id
          : typeof event.session_id === "string"
            ? event.session_id
            : "";
      if (sessionId) {
        sessionRef.current = sessionId;
        setDtSessionId(sessionId);
      }
      return;
    }

    if (event.type === "done") {
      setBusy(false);
      setConnected(true);
      return;
    }

    if (event.type === "error") {
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "system",
          text: event.content || "Something went wrong.",
          stage: event.stage,
          source: event.source,
        },
      ]);
      setBusy(false);
      return;
    }

    if (event.type !== "content" || !event.content) return;

    const text = event.content;
    const stage = event.stage || undefined;
    setMessages((prev) => [
      ...prev,
      {
        id: newMessageId(),
        role: "assistant",
        text,
        stage,
        source: event.source || undefined,
      },
    ]);
    if (looksLikeDualEnded(text, stage)) setClosed(true);
  }, []);

  useEffect(() => {
    const client = new UnifiedWSClient(handleEvent, () => {
      setBusy(false);
      setConnected(false);
    });
    clientRef.current = client;
    setConnected(false);
    client.connect();

    const poll = window.setInterval(() => {
      if (client.connected) {
        setConnected(true);
        setEverConnected(true);
        window.clearInterval(poll);
      }
    }, 100);
    const giveUp = window.setTimeout(() => window.clearInterval(poll), 15_000);

    const retryTimers = retryTimersRef.current;
    return () => {
      window.clearInterval(poll);
      window.clearTimeout(giveUp);
      retryTimers.forEach((timer) => clearTimeout(timer));
      retryTimers.clear();
      client.disconnect();
      clientRef.current = null;
    };
  }, [handleEvent]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages]);

  const sendBlocked = busy || closed;

  function sendWithRetry(payload: StartTurnMessage, attempt = 0) {
    const client = clientRef.current;
    if (!client) return;
    if (client.connected) {
      client.send(payload);
      setConnected(true);
      setEverConnected(true);
      return;
    }
    if (attempt >= 10) {
      setBusy(false);
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "system",
          text: "Connection failed. Please try again.",
        },
      ]);
      return;
    }
    const timer = setTimeout(() => {
      retryTimersRef.current.delete(timer);
      sendWithRetry(payload, attempt + 1);
    }, 200);
    retryTimersRef.current.add(timer);
  }

  function startTurn(content: string) {
    const text = content.trim();
    if (!text || sendBlocked) return;

    setBusy(true);
    const busyWatchdog = setTimeout(() => {
      retryTimersRef.current.delete(busyWatchdog);
      setBusy(false);
    }, 120_000);
    retryTimersRef.current.add(busyWatchdog);

    const payload: StartTurnMessage = {
      type: "start_turn",
      content: text,
      capability: "supervise_dual",
      session_id: sessionRef.current ?? undefined,
      config: {},
    };
    sendWithRetry(payload);
  }

  function handleNewDual() {
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));
    retryTimersRef.current.clear();
    sessionRef.current = null;
    setMessages([]);
    setBusy(false);
    setClosed(false);
    setDtSessionId(null);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <Users className="h-4 w-4 text-[var(--primary)]" aria-hidden />
            Dual
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            Watch AI counselor ↔ visitor · supervisor notes
            {dtSessionId ? (
              <span className="ml-2 font-mono opacity-70">
                session {dtSessionId.slice(0, 8)}…
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleNewDual}
            disabled={!dtSessionId && messages.length === 0}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            New dual
          </button>
          {!connected && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              {everConnected ? "Reconnecting…" : "Connecting…"}
            </span>
          )}
        </div>
      </header>

      {closed && (
        <div
          role="status"
          className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-200"
        >
          This dual has ended. Advance is disabled. Start a New dual to continue.
        </div>
      )}

      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl">
          <DualMessageList messages={messages} />
        </div>
      </div>

      <DualComposer
        busy={busy}
        continueDisabled={sendBlocked}
        endDisabled={sendBlocked || !dtSessionId}
        onContinue={() => startTurn("继续")}
        onEnd={() => startTurn("结束")}
      />
    </div>
  );
}
