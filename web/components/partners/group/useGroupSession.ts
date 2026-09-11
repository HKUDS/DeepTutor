"use client";

/**
 * Live state for one Partner Group session.
 *
 * The transcript is modelled as *rounds with fixed seats* rather than a flat
 * message list. A parallel panel answers one question N times, so the user
 * needs the N answers to read as one round, in a stable order — and each
 * speaker's block must be the same DOM node from "thinking" to "answered", so
 * nothing reorders or jumps when a partner finishes.
 *
 * Ordering therefore follows the group's member list, never arrival order
 * (which is just the backend's asyncio scheduling).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { wsUrl } from "@/lib/api";
import {
  getPartnerGroupHistory,
  type PartnerGroup,
  type PartnerGroupMessage,
  type PartnerInvocation,
} from "@/lib/partner-groups-api";
import { ReconnectingWebSocket } from "@/lib/reconnecting-websocket";
import {
  isNarrationMarker,
  recomputeAnswerContent,
  shouldAppendEventContent,
} from "@/lib/stream";
import type { StreamEvent } from "@/features/chat/model/protocol";

export type SeatStatus = "waiting" | "working" | "done" | "error";

export interface Seat {
  partnerId: string;
  status: SeatStatus;
  /** Speaker-private trace: tool calls, narration, thinking. */
  events: StreamEvent[];
  /** Optimistic body accumulated from stream deltas while working. */
  streamed: string;
  /** The authoritative persisted message, once the turn settles. */
  message?: PartnerGroupMessage;
}

/**
 * Only these two kinds make a round a follow-up.
 *
 * Tested explicitly rather than as "not a plain message": transcripts written
 * before ``kind`` existed carry ``null``, and treating those as follow-ups
 * turned every historical answer into an aside.
 */
function isFollowupKind(kind: string | null | undefined): boolean {
  return kind === "invocation_question" || kind === "invocation_reply";
}

export interface Round {
  turnId: string;
  /** The human message that opened this round (absent for follow-up rounds). */
  user?: PartnerGroupMessage;
  seats: Seat[];
  /** True for an approved partner-to-partner exchange, rendered as an aside. */
  followup: boolean;
  /** Set while this round is the one currently running. */
  live: boolean;
  /** The user stopped this round before every speaker finished. */
  stopped?: boolean;
}

interface LiveTurn {
  turnId: string;
  /** The session that started this turn; a thread switch retires it. */
  sessionKey: string;
  targets: string[];
  seats: Map<string, Seat>;
  followup: boolean;
}

type GroupFrame =
  | { type: "user_message"; message: PartnerGroupMessage }
  | { type: "partner_started"; partner_id: string; invocation_id?: string }
  | {
      type: "partner_trace";
      turn_id: string;
      partner_id: string;
      invocation_id?: string;
      event: StreamEvent;
    }
  | { type: "partner_message"; message: PartnerGroupMessage }
  | { type: "invocation_updated"; invocation: PartnerInvocation }
  | { type: "done"; result?: Record<string, unknown> }
  | { type: "cancelled"; content?: string }
  | { type: "error"; content: string };

/**
 * Grow a seat's visible body from one trace event.
 *
 * Answer text and narration arrive on the same ``content`` channel; a round is
 * only revealed as narration when its marker lands, so the body is appended
 * optimistically and recomputed when that happens. This is the same rule the
 * product chat uses (``lib/stream``), so a Partner's body reads identically in
 * both surfaces.
 */
function growBody(seat: Seat, event: StreamEvent): string {
  if (isNarrationMarker(event)) {
    return recomputeAnswerContent([...seat.events, event]);
  }
  return shouldAppendEventContent(event)
    ? seat.streamed + (event.content || "")
    : seat.streamed;
}

function emptySeat(partnerId: string): Seat {
  return { partnerId, status: "waiting", events: [], streamed: "" };
}

export function useGroupSession(group: PartnerGroup, sessionKey: string) {
  const [messages, setMessages] = useState<PartnerGroupMessage[]>([]);
  const [rawLive, setLive] = useState<LiveTurn | null>(null);
  // Switching threads retires a turn started by the previous one, declaratively
  // rather than by resetting state inside an effect.
  const live = rawLive && rawLive.sessionKey === sessionKey ? rawLive : null;
  const [stoppedTurns, setStoppedTurns] = useState<Set<string>>(new Set());
  const [connected, setConnected] = useState(false);
  /** Which session's history has landed. Deriving ``loading`` from it means
   *  switching sessions is loading again without an imperative reset. */
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  /** Invocation ids with an approve/reject request in flight. */
  const [pendingActions, setPendingActions] = useState<Set<string>>(new Set());

  const socketRef = useRef<ReconnectingWebSocket | null>(null);
  /** A user-initiated invocation runs immediately: they *are* the approval. */
  const autoRunRef = useRef<{ requester: string; target: string } | null>(null);
  const historyReadyRef = useRef(false);

  const attach = useCallback(
    (socket: ReconnectingWebSocket | null) => {
      socket?.send(
        JSON.stringify({ action: "attach", session_key: sessionKey }),
      );
    },
    [sessionKey],
  );

  useEffect(() => {
    let cancelled = false;
    historyReadyRef.current = false;
    void getPartnerGroupHistory(group.group_id, sessionKey)
      .then((history) => {
        if (cancelled) return;
        setMessages(history);
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoadedKey(sessionKey);
        historyReadyRef.current = true;
        // Re-attaching after history lands lets an in-flight turn started
        // before this mount (or before a refresh) replay into the new socket.
        attach(socketRef.current);
      });
    return () => {
      cancelled = true;
    };
  }, [attach, group.group_id, sessionKey]);

  const handleFrame = useCallback(
    (frame: GroupFrame) => {
      switch (frame.type) {
        case "user_message": {
          const message = frame.message;
          setMessages((current) =>
            current.some((item) => item.event_id === message.event_id)
              ? current
              : [...current, message],
          );
          // ``mentions`` is the backend's resolved target list, so the seats
          // for this round are known before any partner starts working.
          const targets = message.mentions.length
            ? message.mentions
            : group.member_ids;
          setLive({
            sessionKey,
            turnId: message.turn_id,
            targets,
            seats: new Map(targets.map((id) => [id, emptySeat(id)])),
            followup: false,
          });
          setError("");
          return;
        }
        case "partner_started": {
          setLive((current) => {
            // A follow-up round has no user message to open it, so the first
            // signal that it exists is the invoked partner starting.
            const base: LiveTurn = current ?? {
              turnId: "",
              sessionKey,
              targets: [frame.partner_id],
              seats: new Map(),
              followup: Boolean(frame.invocation_id),
            };
            const seats = new Map(base.seats);
            const seat =
              seats.get(frame.partner_id) ?? emptySeat(frame.partner_id);
            seats.set(frame.partner_id, { ...seat, status: "working" });
            const targets = base.targets.includes(frame.partner_id)
              ? base.targets
              : [...base.targets, frame.partner_id];
            return { ...base, targets, seats };
          });
          return;
        }
        case "partner_trace": {
          setLive((current) => {
            if (!current) return current;
            const seats = new Map(current.seats);
            const seat =
              seats.get(frame.partner_id) ?? emptySeat(frame.partner_id);
            seats.set(frame.partner_id, {
              ...seat,
              status: "working",
              streamed: growBody(seat, frame.event),
              events: [...seat.events, frame.event],
            });
            return {
              ...current,
              turnId: current.turnId || frame.turn_id,
              seats,
            };
          });
          return;
        }
        case "partner_message": {
          const message = frame.message;
          setMessages((current) =>
            current.some((item) => item.event_id === message.event_id)
              ? current
              : [...current, message],
          );
          setLive((current) => {
            if (!current) return current;
            const seats = new Map(current.seats);
            seats.delete(message.author_id);
            return { ...current, seats };
          });
          return;
        }
        case "invocation_updated": {
          const invocation = frame.invocation;
          // The user asked for this one, so skip the approval step they would
          // otherwise have to click on their own request.
          const wanted = autoRunRef.current;
          if (
            wanted &&
            invocation.status === "pending" &&
            invocation.requester_partner_id === wanted.requester &&
            invocation.target_partner_id === wanted.target
          ) {
            autoRunRef.current = null;
            socketRef.current?.send(
              JSON.stringify({
                action: "approve_invocation",
                invocation_id: invocation.invocation_id,
                session_key: sessionKey,
              }),
            );
          }
          setMessages((current) =>
            current.map((message) =>
              message.invocation_id === invocation.invocation_id
                ? { ...message, invocation }
                : message,
            ),
          );
          setPendingActions((current) => {
            if (!current.has(invocation.invocation_id)) return current;
            const next = new Set(current);
            next.delete(invocation.invocation_id);
            return next;
          });
          return;
        }
        case "cancelled": {
          setLive(null);
          setPendingActions(new Set());
          return;
        }
        case "done": {
          setLive(null);
          setPendingActions(new Set());
          return;
        }
        case "error": {
          setLive(null);
          setPendingActions(new Set());
          setError(frame.content);
          return;
        }
      }
    },
    // ``sessionKey`` only stamps new turns; the handler is reached through a
    // ref below, so widening this does not touch the socket's lifetime.
    [group.member_ids, sessionKey],
  );

  // The socket outlives roster edits, so the handler is reached through a ref
  // instead of being a dependency — otherwise changing a member would drop and
  // re-open the connection mid-discussion.
  const handleFrameRef = useRef(handleFrame);
  useEffect(() => {
    handleFrameRef.current = handleFrame;
  }, [handleFrame]);

  useEffect(() => {
    const socket = new ReconnectingWebSocket(
      wsUrl(`/ws/partner-groups/${encodeURIComponent(group.group_id)}`),
      {
        onOpen: () => {
          setConnected(true);
          if (historyReadyRef.current) attach(socket);
        },
        onDisconnect: () => setConnected(false),
        onError: () => setConnected(false),
        onMessage: (event) => {
          try {
            handleFrameRef.current(
              JSON.parse(String(event.data)) as GroupFrame,
            );
          } catch {
            // A malformed frame must not tear down the session.
          }
        },
      },
    );
    socketRef.current = socket;
    socket.start();
    return () => {
      socket.stop();
      socketRef.current = null;
    };
  }, [attach, group.group_id]);

  /** Rounds derived from persisted messages, merged with the live turn. */
  const rounds = useMemo<Round[]>(() => {
    const order = group.member_ids;
    const byTurn = new Map<string, Round>();
    for (const message of messages) {
      let round = byTurn.get(message.turn_id);
      if (!round) {
        round = {
          turnId: message.turn_id,
          seats: [],
          followup: isFollowupKind(message.kind),
          live: false,
          stopped: stoppedTurns.has(message.turn_id),
        };
        byTurn.set(message.turn_id, round);
      }
      if (message.role === "user") {
        round.user = message;
        continue;
      }
      if (message.kind === "round_stopped") {
        // Server-side record of a user cancellation: round metadata, not a
        // speaker, and what makes the marker survive a refresh.
        round.stopped = true;
        continue;
      }
      if (isFollowupKind(message.kind)) round.followup = true;
      round.seats.push({
        partnerId: message.author_id,
        status: message.error ? "error" : "done",
        events: message.events ?? [],
        streamed: "",
        message,
      });
    }

    if (live) {
      const round =
        byTurn.get(live.turnId) ??
        (() => {
          const created: Round = {
            turnId: live.turnId || "live",
            seats: [],
            followup: live.followup,
            live: true,
          };
          byTurn.set(created.turnId, created);
          return created;
        })();
      round.live = true;
      round.seats = [...round.seats, ...live.seats.values()];
    }

    const seatRank = (seat: Seat) => {
      const index = order.indexOf(seat.partnerId);
      return index === -1 ? order.length : index;
    };

    /**
     * Which pass of the round a seat belongs to.
     *
     * Debate puts the same speaker on the panel twice, so ordering by member
     * alone would interleave the passes (A-opening, A-rebuttal, B-opening…)
     * and destroy the actual chronology. A live seat carries no message yet,
     * so its pass is inferred from how many times that speaker has already
     * landed one in this round — which is exactly what makes a parallel
     * round's live seats keep their fixed position instead of jumping.
     */
    const passRank = (seat: Seat, siblings: Seat[]) => {
      const kind = seat.message?.kind;
      if (kind === "round_summary") return 2;
      if (kind === "debate_rebuttal") return 1;
      if (seat.message) return 0;
      const spoken = siblings.filter(
        (item) => item.message && item.partnerId === seat.partnerId,
      ).length;
      return Math.min(spoken, 2);
    };

    return [...byTurn.values()].map((round) => ({
      ...round,
      // Follow-up rounds are a Q&A pair whose chronological order carries the
      // meaning (question then answer), so only panel rounds get seat order.
      seats: round.followup
        ? round.seats
        : [...round.seats].sort(
            (a, b) =>
              passRank(a, round.seats) - passRank(b, round.seats) ||
              seatRank(a) - seatRank(b),
          ),
    }));
  }, [group.member_ids, live, messages, stoppedTurns]);

  const send = useCallback(
    (content: string, mentions: string[] | null) => {
      const socket = socketRef.current;
      if (!socket?.connected) return false;
      return socket.send(
        JSON.stringify({ content, session_key: sessionKey, mentions }),
      );
    },
    [sessionKey],
  );

  const actOnInvocation = useCallback(
    (invocationId: string, action: "approve" | "reject") => {
      const socket = socketRef.current;
      if (!socket?.connected || pendingActions.has(invocationId)) return false;
      setPendingActions((current) => new Set(current).add(invocationId));
      const ok = socket.send(
        JSON.stringify({
          action:
            action === "approve" ? "approve_invocation" : "reject_invocation",
          invocation_id: invocationId,
          session_key: sessionKey,
        }),
      );
      if (!ok) {
        setPendingActions((current) => {
          const next = new Set(current);
          next.delete(invocationId);
          return next;
        });
      }
      return ok;
    },
    [pendingActions, sessionKey],
  );

  /** Ask one Partner to respond to another, on the user's initiative. */
  const askPeer = useCallback(
    (requesterId: string, targetId: string, question: string) => {
      const socket = socketRef.current;
      if (!socket?.connected) return false;
      autoRunRef.current = { requester: requesterId, target: targetId };
      const ok = socket.send(
        JSON.stringify({
          action: "create_invocation",
          session_key: sessionKey,
          requester_partner_id: requesterId,
          target_partner_id: targetId,
          question,
        }),
      );
      if (!ok) autoRunRef.current = null;
      return ok;
    },
    [sessionKey],
  );

  /** Ask one member to close a round with consensus / disagreement / advice. */
  const summarizeRound = useCallback(
    (turnId: string, partnerId: string) => {
      const socket = socketRef.current;
      if (!socket?.connected) return false;
      return socket.send(
        JSON.stringify({
          action: "summarize_round",
          session_key: sessionKey,
          turn_id: turnId,
          partner_id: partnerId,
        }),
      );
    },
    [sessionKey],
  );

  const cancel = useCallback(() => {
    const socket = socketRef.current;
    if (!socket?.connected) return false;
    const ok = socket.send(
      JSON.stringify({ action: "cancel", session_key: sessionKey }),
    );
    // Remember the round so the transcript can say it was stopped: otherwise
    // the user is left with their question and no trace of what happened.
    if (ok && live) {
      const turnId = live.turnId;
      setStoppedTurns((current) => new Set(current).add(turnId));
    }
    return ok;
  }, [live, sessionKey]);

  /**
   * How many addressed partners have already answered this round.
   *
   * A debate runs two passes over the same speakers, so the counter would
   * appear to fall back to zero halfway through. ``clash`` says which pass is
   * running — everyone having already landed a message means this is the
   * second one — so the label can say so instead of looking like a regression.
   */
  const progress = useMemo(() => {
    if (!live) return null;
    const total = live.targets.length;
    const answered = messages.filter(
      (message) =>
        message.turn_id === live.turnId && message.role === "partner",
    ).length;
    return {
      done: total - live.seats.size,
      total,
      clash: total > 0 && answered >= total,
    };
  }, [live, messages]);

  return {
    rounds,
    running: Boolean(live),
    progress,
    connected,
    loading: loadedKey !== sessionKey,
    error,
    setError,
    pendingActions,
    send,
    actOnInvocation,
    askPeer,
    summarizeRound,
    cancel,
  };
}
