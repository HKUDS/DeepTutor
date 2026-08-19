"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ClipboardList, Loader2 } from "lucide-react";
import IntakeMessageList from "@/components/intake/IntakeMessageList";
import WhisperComposer from "@/components/whisper/WhisperComposer";
import WhisperRoomChip from "@/components/whisper/WhisperRoomChip";
import {
  UnifiedWSClient,
  type StartTurnMessage,
  type StreamEvent,
} from "@/lib/unified-ws";
import {
  filterMessagesForSeat,
  looksLikeCrisisRedirect,
  looksLikeIntakeRoomEnded,
  looksLikeIntakeTraineeCrisisSummary,
  parseRoomIdFromContent,
  type IntakeMessage,
  type IntakeSeat,
} from "@/lib/intake-transcript";
import type { WhisperSeat } from "@/lib/whisper-transcript";

function newMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

type ActiveSeat = Extract<IntakeSeat, "visitor" | "trainee">;

export default function IntakePage() {
  const [seat, setSeat] = useState<IntakeSeat>("visitor");
  const [roomId, setRoomId] = useState<string | null>(null);
  const [messages, setMessages] = useState<IntakeMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [crisisHit, setCrisisHit] = useState(false);
  const [roomClosed, setRoomClosed] = useState(false);
  const [draft, setDraft] = useState("");
  const [dtSessionId, setDtSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [everConnected, setEverConnected] = useState(false);

  const clientRef = useRef<UnifiedWSClient | null>(null);
  const seatRef = useRef<IntakeSeat>(seat);
  const roomIdRef = useRef<string | null>(roomId);
  const sessionBySeatRef = useRef<Record<ActiveSeat, string | null>>({
    visitor: null,
    trainee: null,
  });
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    seatRef.current = seat;
  }, [seat]);

  useEffect(() => {
    roomIdRef.current = roomId;
  }, [roomId]);

  const handleEvent = useCallback((event: StreamEvent) => {
    if (event.type === "session" || event.type === "session_meta") {
      const metadata = (event.metadata || {}) as Record<string, unknown>;
      const sessionId =
        typeof metadata.session_id === "string"
          ? metadata.session_id
          : typeof event.session_id === "string"
            ? event.session_id
            : "";
      if (sessionId && seatRef.current !== "supervisor") {
        sessionBySeatRef.current[seatRef.current] = sessionId;
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
      const text = event.content || "Something went wrong.";
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "system",
          text,
          stage: event.stage,
          source: event.source,
        },
      ]);
      setBusy(false);
      return;
    }

    if (event.type !== "content" || !event.content) return;

    const text = event.content;
    setMessages((prev) => [
      ...prev,
      {
        id: newMessageId(),
        role: "assistant",
        text,
        stage: event.stage || undefined,
        source: event.source || undefined,
      },
    ]);

    if (!roomIdRef.current) {
      const parsed = parseRoomIdFromContent(text);
      if (parsed) setRoomId(parsed);
    }

    if (
      looksLikeCrisisRedirect(text) ||
      looksLikeIntakeTraineeCrisisSummary(text)
    ) {
      setCrisisHit(true);
      setRoomClosed(true);
    }
    if (looksLikeIntakeRoomEnded(text)) {
      setRoomClosed(true);
    }
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
  }, [messages, seat]);

  const visibleMessages = useMemo(
    () => filterMessagesForSeat(messages, seat),
    [messages, seat],
  );

  const readOnly = seat === "supervisor";
  const composerSeat: WhisperSeat = seat === "trainee" ? "trainee" : "visitor";
  const traineeNeedsRoom = seat === "trainee" && !roomId;
  const roomLocked = crisisHit || roomClosed;
  const inputDisabled = roomLocked || readOnly;
  const sendBlocked = busy || roomLocked || traineeNeedsRoom || readOnly;

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

  function startTurn(content: string, options?: { hideOptimistic?: boolean }) {
    const text = content.trim();
    if (!text || sendBlocked || seat === "supervisor") return;

    if (!options?.hideOptimistic) {
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "user",
          text,
          localSeat: seat,
        },
      ]);
    }

    setDraft("");
    setBusy(true);

    const busyWatchdog = setTimeout(() => {
      retryTimersRef.current.delete(busyWatchdog);
      setBusy(false);
    }, 120_000);
    retryTimersRef.current.add(busyWatchdog);

    const capability = seat === "visitor" ? "intake_visitor" : "intake_trainee";
    const payload: StartTurnMessage = {
      type: "start_turn",
      content: text,
      capability,
      session_id: sessionBySeatRef.current[seat] ?? undefined,
      config: roomId ? { room_id: roomId } : {},
    };
    sendWithRetry(payload);
  }

  function handleSend() {
    startTurn(draft);
  }

  function handleEnd() {
    if (seat !== "trainee" || !roomId || sendBlocked) return;
    startTurn("结束");
  }

  function switchSeat(next: IntakeSeat) {
    setSeat(next);
    if (next === "supervisor") {
      return;
    }
    setDtSessionId(sessionBySeatRef.current[next]);
  }

  function handleNewRoom() {
    retryTimersRef.current.forEach((timer) => clearTimeout(timer));
    retryTimersRef.current.clear();
    sessionBySeatRef.current = { visitor: null, trainee: null };
    setMessages([]);
    setDraft("");
    setBusy(false);
    setCrisisHit(false);
    setRoomClosed(false);
    setRoomId(null);
    setDtSessionId(null);
    setSeat("visitor");
  }

  const canNewRoom = Boolean(roomId || roomClosed || crisisHit);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <ClipboardList
              className="h-4 w-4 text-[var(--primary)]"
              aria-hidden
            />
            Intake
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            Live intake supervision · visitor, trainee counselor, supervisor
            {dtSessionId ? (
              <span className="ml-2 font-mono opacity-70">
                session {dtSessionId.slice(0, 8)}…
              </span>
            ) : null}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {roomId ? <WhisperRoomChip roomId={roomId} /> : null}
          <button
            type="button"
            onClick={handleNewRoom}
            disabled={!canNewRoom}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            New room
          </button>
          <div
            role="tablist"
            aria-label="Seat"
            className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--background)] p-0.5"
          >
            {(["visitor", "trainee", "supervisor"] as const).map((value) => {
              const active = seat === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => switchSeat(value)}
                  className={`rounded-[10px] px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                    active
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {value}
                </button>
              );
            })}
          </div>
          {!connected && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              {everConnected ? "Reconnecting…" : "Connecting…"}
            </span>
          )}
        </div>
      </header>

      {(crisisHit || roomClosed) && (
        <div
          role="status"
          className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-200"
        >
          {crisisHit
            ? "Crisis redirect detected. Sending is disabled for this room."
            : "This intake session has ended. Sending is disabled."}{" "}
          You can still copy the room id.
        </div>
      )}

      {seat === "trainee" && !roomId && (
        <div
          role="status"
          className="border-b border-[var(--border)] bg-[var(--background)] px-4 py-2 text-xs text-[var(--muted-foreground)]"
        >
          Open the room as Visitor first.
        </div>
      )}

      {seat === "supervisor" && (
        <div
          role="status"
          className="border-b border-sky-500/30 bg-sky-500/10 px-4 py-2 text-xs text-sky-800 dark:text-sky-200"
        >
          Supervisor seat is read-only. Switch to Visitor or Trainee to send
          messages.
        </div>
      )}

      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl">
          <IntakeMessageList messages={visibleMessages} seat={seat} />
        </div>
      </div>

      {!readOnly && (
        <WhisperComposer
          seat={composerSeat}
          draft={draft}
          busy={busy}
          sendDisabled={sendBlocked}
          inputDisabled={inputDisabled}
          showEndButton={seat === "trainee"}
          endDisabled={sendBlocked || !roomId}
          onDraftChange={setDraft}
          onSend={handleSend}
          onEnd={handleEnd}
        />
      )}
    </div>
  );
}
