"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { HeartHandshake, Loader2 } from "lucide-react";
import CounselAskUserCard from "@/components/counsel/CounselAskUserCard";
import CounselComposer from "@/components/counsel/CounselComposer";
import CounselMessageList, {
  type CounselMessage,
} from "@/components/counsel/CounselMessageList";
import {
  extractAskUserPayload,
  type AskUserPayload,
} from "@/components/chat/home/AskUserOptions";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import {
  looksLikeCounselSessionEnded,
  looksLikeCrisisRedirect,
} from "@/lib/counsel-transcript";
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

function askUserPayloadFromToolCall(event: StreamEvent): AskUserPayload | null {
  const meta = (event.metadata || {}) as Record<string, unknown>;
  const args = meta.args;
  if (!args || typeof args !== "object") return null;
  const questions = (args as { questions?: unknown }).questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;
  return {
    intro: null,
    questions: questions.map((q, idx) => {
      const row = q as Record<string, unknown>;
      return {
        id: String(row.id || `q${idx}`),
        prompt: String(row.prompt || ""),
        header: typeof row.header === "string" ? row.header : null,
        multi_select: false,
        options: [],
        allow_free_text: true,
        placeholder: null,
      };
    }),
  };
}

export default function CounselPage() {
  const [messages, setMessages] = useState<CounselMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [dtSessionId, setDtSessionId] = useState<string | null>(null);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [everConnected, setEverConnected] = useState(false);
  const [crisisHit, setCrisisHit] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [pendingAskUser, setPendingAskUser] = useState<AskUserPayload | null>(
    null,
  );

  const clientRef = useRef<UnifiedWSClient | null>(null);
  const sessionRef = useRef<string | null>(null);
  const turnIdRef = useRef<string | null>(null);
  const turnEventsRef = useRef<StreamEvent[]>([]);
  const assistantBufferRef = useRef<{ id: string; stage: string } | null>(null);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    sessionRef.current = dtSessionId;
  }, [dtSessionId]);

  useEffect(() => {
    turnIdRef.current = activeTurnId;
  }, [activeTurnId]);

  const appendAssistantContent = useCallback((text: string, stage: string) => {
    const normalized = stage || "responding";
    if (
      assistantBufferRef.current &&
      assistantBufferRef.current.stage === normalized
    ) {
      const targetId = assistantBufferRef.current.id;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === targetId ? { ...m, text: m.text + text, stage: normalized } : m,
        ),
      );
      return;
    }
    const id = newMessageId();
    assistantBufferRef.current = { id, stage: normalized };
    setMessages((prev) => [
      ...prev,
      { id, role: "assistant", text, stage: normalized },
    ]);
  }, []);

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      turnEventsRef.current = [...turnEventsRef.current, event];

      if (event.turn_id) {
        turnIdRef.current = event.turn_id;
        setActiveTurnId(event.turn_id);
      }

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
        const tid =
          typeof metadata.turn_id === "string"
            ? metadata.turn_id
            : event.turn_id;
        if (tid) {
          turnIdRef.current = tid;
          setActiveTurnId(tid);
        }
        return;
      }

      if (event.type === "done") {
        assistantBufferRef.current = null;
        const card = extractAskUserPayload(turnEventsRef.current);
        if (card && !card.resolved) {
          setPendingAskUser(card.payload);
          setBusy(false);
        } else {
          setPendingAskUser(null);
          setBusy(false);
        }
        setConnected(true);
        return;
      }

      if (event.type === "error") {
        assistantBufferRef.current = null;
        setMessages((prev) => [
          ...prev,
          {
            id: newMessageId(),
            role: "system",
            text: event.content || "Something went wrong.",
          },
        ]);
        setBusy(false);
        setPendingAskUser(null);
        return;
      }

      if (event.type === "tool_call" && event.content === "ask_user") {
        const payload = askUserPayloadFromToolCall(event);
        if (payload) setPendingAskUser(payload);
        return;
      }

      if (event.type === "progress") {
        const meta = event.metadata || {};
        if (meta.ask_user_resolved) {
          setPendingAskUser(null);
        }
        return;
      }

      if (event.type !== "content" || !event.content) return;

      const text = event.content;
      const stage = event.stage || "responding";
      appendAssistantContent(text, stage);

      if (looksLikeCrisisRedirect(text)) {
        setCrisisHit(true);
        setSessionEnded(true);
        setPendingAskUser(null);
      }
      if (looksLikeCounselSessionEnded(text)) {
        setSessionEnded(true);
        setPendingAskUser(null);
      }
    },
    [appendAssistantContent],
  );

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
  }, [messages, pendingAskUser]);

  const roomLocked = crisisHit || sessionEnded;
  const awaitingAskUser =
    Boolean(pendingAskUser) &&
    Boolean(activeTurnId) &&
    hasPendingAskUser(turnEventsRef.current, activeTurnId);
  const sendBlocked = busy || roomLocked || awaitingAskUser;

  function sendWithRetry(
    payload: StartTurnMessage | { type: "submit_user_reply"; turn_id: string; answers?: Array<{ questionId: string; text: string }>; text?: string },
    attempt = 0,
  ) {
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
    if (!text || sendBlocked) return;

    turnEventsRef.current = [];
    assistantBufferRef.current = null;
    setPendingAskUser(null);

    setMessages((prev) => [
      ...prev,
      { id: newMessageId(), role: "user", text },
    ]);
    setDraft("");
    setBusy(true);
    const busyWatchdog = setTimeout(() => {
      retryTimersRef.current.delete(busyWatchdog);
      setBusy(false);
    }, 180_000);
    retryTimersRef.current.add(busyWatchdog);

    sendWithRetry({
      type: "start_turn",
      content: text,
      capability: "counsel",
      session_id: sessionRef.current ?? undefined,
      language: "zh",
      config: {},
    });
  }

  function submitAskUser(answers: Array<{ questionId: string; text: string }>) {
    const turnId = turnIdRef.current;
    if (!turnId || busy || roomLocked) return;
    setBusy(true);
    setPendingAskUser(null);
    sendWithRetry({
      type: "submit_user_reply",
      turn_id: turnId,
      answers,
    });
  }

  function handleNewSession() {
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));
    retryTimersRef.current.clear();
    sessionRef.current = null;
    turnIdRef.current = null;
    turnEventsRef.current = [];
    assistantBufferRef.current = null;
    setMessages([]);
    setDraft("");
    setBusy(false);
    setDtSessionId(null);
    setActiveTurnId(null);
    setCrisisHit(false);
    setSessionEnded(false);
    setPendingAskUser(null);
  }

  const canNewSession = Boolean(dtSessionId || messages.length > 0 || crisisHit || sessionEnded);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <HeartHandshake className="h-4 w-4 text-[var(--primary)]" aria-hidden />
            Counsel
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            Visitor-facing counseling (Phase 2)
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
            onClick={handleNewSession}
            disabled={!canNewSession}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            New session
          </button>
          {!connected && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              {everConnected ? "Reconnecting…" : "Connecting…"}
            </span>
          )}
        </div>
      </header>

      {(crisisHit || sessionEnded) && (
        <div
          role="status"
          className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-200"
        >
          {crisisHit
            ? "Crisis redirect detected. This session cannot continue as counseling."
            : "This counseling session has ended. Start a new session to continue."}
        </div>
      )}

      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl space-y-4">
          <CounselMessageList messages={messages} />
          {awaitingAskUser && pendingAskUser ? (
            <CounselAskUserCard
              payload={pendingAskUser}
              busy={busy}
              onSubmit={submitAskUser}
            />
          ) : null}
        </div>
      </div>

      <CounselComposer
        draft={draft}
        busy={busy}
        sendDisabled={sendBlocked}
        inputDisabled={roomLocked}
        onDraftChange={setDraft}
        onSend={startTurn}
      />
    </div>
  );
}
