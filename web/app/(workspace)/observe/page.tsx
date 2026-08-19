"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Eye, Loader2 } from "lucide-react";
import ObserveComposer from "@/components/observe/ObserveComposer";
import ObserveMessageList, {
  type ObserveMessage,
} from "@/components/observe/ObserveMessageList";
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

export default function ObservePage() {
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ObserveMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
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

  useEffect(() => {
    const counselId = searchParams.get("counsel_id")?.trim();
    if (counselId) {
      setDraft(counselId);
    }
  }, [searchParams]);

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

    setMessages((prev) => [
      ...prev,
      {
        id: newMessageId(),
        role: "assistant",
        text: event.content,
        stage: event.stage || undefined,
        source: event.source || undefined,
      },
    ]);
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

  function startTurn() {
    const text = draft.trim();
    if (!text || busy) return;

    setMessages((prev) => [
      ...prev,
      { id: newMessageId(), role: "user", text },
    ]);
    setDraft("");
    setBusy(true);
    const busyWatchdog = setTimeout(() => {
      retryTimersRef.current.delete(busyWatchdog);
      setBusy(false);
    }, 120_000);
    retryTimersRef.current.add(busyWatchdog);

    const payload: StartTurnMessage = {
      type: "start_turn",
      content: text,
      capability: "supervise_observe",
      session_id: sessionRef.current ?? undefined,
      config: {},
    };
    sendWithRetry(payload);
  }

  function handleNewObserve() {
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));
    retryTimersRef.current.clear();
    sessionRef.current = null;
    setMessages([]);
    setDraft("");
    setBusy(false);
    setDtSessionId(null);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <Eye className="h-4 w-4 text-[var(--primary)]" aria-hidden />
            Observe
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            One-shot debrief of a closed visitor counsel session
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
            onClick={handleNewObserve}
            disabled={!dtSessionId && messages.length === 0}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            New observe
          </button>
          {!connected && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              {everConnected ? "Reconnecting…" : "Connecting…"}
            </span>
          )}
        </div>
      </header>

      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl">
          <ObserveMessageList messages={messages} />
        </div>
      </div>

      <ObserveComposer
        draft={draft}
        busy={busy}
        sendDisabled={busy}
        onDraftChange={setDraft}
        onSend={startTurn}
      />
    </div>
  );
}
