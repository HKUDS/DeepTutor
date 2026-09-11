"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchProgressEvents, type MasteryEvent } from "@/lib/learning-api";
import {
  MasteryTopicSocket,
  type MasterySocketEnvelope,
} from "@/lib/mastery-ws";

export type MasteryConnectionState = "connecting" | "live" | "offline";

interface SocketStatus {
  pathId: string | null;
  connection: MasteryConnectionState;
  error: string | null;
}

export interface MasteryPathActivity {
  events: MasteryEvent[];
  revision: number;
  /** Changes for same-revision signals such as a newly bound session. */
  signal: number;
  connection: MasteryConnectionState;
  error: string | null;
  /** Reconcile from durable storage immediately. */
  refresh: () => void;
}

/** The feed is stamped with its path so a route switch never flashes history. */
export interface ActivityFeed {
  pathId: string | null;
  events: MasteryEvent[];
  revision: number;
  signal: number;
}

export const EMPTY_FEED: ActivityFeed = {
  pathId: null,
  events: [],
  revision: 0,
  signal: 0,
};

function eventIdentity(event: MasteryEvent): string {
  return event.id
    ? `id:${event.id}`
    : [
        event.revision,
        event.event_type,
        event.session_id,
        event.turn_id,
        event.created_at,
      ].join(":");
}

/** Fold durable events into one sorted, duplicate-free per-topic feed. */
export function mergeEventBatch(
  previous: ActivityFeed,
  pathId: string,
  since: number,
  batch: MasteryEvent[],
  headRevision?: number,
): ActivityFeed {
  if (batch.length === 0 && headRevision === undefined) return previous;
  const continues = since > 0 && previous.pathId === pathId;
  const candidates = continues ? [...previous.events, ...batch] : batch;
  const seen = new Set<string>();
  const events = candidates
    .filter((event) => {
      const identity = eventIdentity(event);
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    })
    .sort(
      (left, right) => left.revision - right.revision || left.id - right.id,
    );
  const revision = Math.max(
    continues ? previous.revision : 0,
    latestRevision(since, events),
    headRevision ?? 0,
  );

  if (
    previous.pathId === pathId &&
    previous.events.length === events.length &&
    previous.events.every((event, index) => event === events[index]) &&
    previous.revision === revision
  ) {
    return previous;
  }
  return {
    pathId,
    events,
    revision,
    signal: previous.pathId === pathId ? previous.signal : 0,
  };
}

export function mergeSocketEnvelope(
  previous: ActivityFeed,
  pathId: string,
  envelope: MasterySocketEnvelope,
): ActivityFeed {
  const since = previous.pathId === pathId ? previous.revision : 0;
  const merged = mergeEventBatch(
    previous,
    pathId,
    since,
    envelope.events,
    envelope.revision,
  );
  return {
    ...merged,
    // A session binding is committed product state but does not rewrite the
    // learning aggregate. Keep a distinct signal so session lists still react.
    signal: (previous.pathId === pathId ? previous.signal : 0) + 1,
  };
}

/** Where the next durable read should start after consuming a batch. */
export function latestRevision(since: number, batch: MasteryEvent[]): number {
  return batch.reduce(
    (highest, event) => Math.max(highest, event.revision),
    since,
  );
}

/**
 * Follow one topic via its dedicated WebSocket.
 *
 * The socket registers before server replay, resumes from the last committed
 * revision, and reconnects with exponential backoff. Focus, visibility and an
 * explicit refresh also reconcile against SQLite over REST, so a proxy that
 * cannot upgrade WebSockets degrades to fresh-on-return instead of stale UI.
 */
export function useMasteryPathActivity(
  pathId: string | null,
): MasteryPathActivity {
  const [feed, setFeed] = useState<ActivityFeed>(EMPTY_FEED);
  const [socketStatus, setSocketStatus] = useState<SocketStatus>({
    pathId: null,
    connection: "offline",
    error: null,
  });
  const cursorRef = useRef<{ pathId: string | null; revision: number }>({
    pathId: null,
    revision: 0,
  });
  const reconcileRef = useRef<() => void>(() => {});

  const refresh = useCallback(() => reconcileRef.current(), []);

  useEffect(() => {
    if (!pathId) return;

    let disposed = false;
    let reconciliation: AbortController | null = null;
    const initialRevision =
      cursorRef.current.pathId === pathId ? cursorRef.current.revision : 0;
    cursorRef.current = { pathId, revision: initialRevision };

    const reconcile = () => {
      if (disposed) return;
      reconciliation?.abort();
      reconciliation = new AbortController();
      const since =
        cursorRef.current.pathId === pathId ? cursorRef.current.revision : 0;
      void fetchProgressEvents(pathId, since, {
        signal: reconciliation.signal,
      })
        .then((batch) => {
          if (disposed) return;
          const revision = latestRevision(since, batch);
          cursorRef.current = { pathId, revision };
          setFeed((previous) =>
            mergeEventBatch(previous, pathId, since, batch, revision),
          );
        })
        .catch((reason: unknown) => {
          if (disposed || reconciliation?.signal.aborted) return;
          setSocketStatus({
            pathId,
            connection: "offline",
            error:
              reason instanceof Error
                ? reason.message
                : "Live update unavailable",
          });
        });
    };
    reconcileRef.current = reconcile;

    const socket = new MasteryTopicSocket(
      pathId,
      {
        onEnvelope: (envelope) => {
          if (disposed) return;
          cursorRef.current = {
            pathId,
            revision: Math.max(cursorRef.current.revision, envelope.revision),
          };
          setFeed((previous) =>
            mergeSocketEnvelope(previous, pathId, envelope),
          );
        },
        onConnecting: () => {
          if (!disposed) {
            setSocketStatus({ pathId, connection: "connecting", error: null });
          }
        },
        onLive: () => {
          if (disposed) return;
          setSocketStatus({ pathId, connection: "live", error: null });
        },
        onDisconnect: () => {
          if (disposed) return;
          setSocketStatus({ pathId, connection: "offline", error: null });
          reconcile();
        },
        onError: (message) => {
          if (disposed) return;
          setSocketStatus({ pathId, connection: "offline", error: message });
        },
      },
      initialRevision,
      {
        shouldReconnect: () =>
          !disposed &&
          (typeof document === "undefined" ||
            document.visibilityState === "visible"),
      },
    );
    socket.start();

    const wake = () => {
      if (document.visibilityState !== "visible") return;
      socket.wake();
      reconcile();
    };
    window.addEventListener("focus", wake);
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", wake);

    return () => {
      disposed = true;
      reconciliation?.abort();
      socket.stop();
      reconcileRef.current = () => {};
      window.removeEventListener("focus", wake);
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [pathId]);

  const current = feed.pathId === pathId ? feed : EMPTY_FEED;
  const status =
    socketStatus.pathId === pathId
      ? socketStatus
      : {
          pathId,
          connection: pathId ? ("connecting" as const) : ("offline" as const),
          error: null,
        };
  return {
    events: current.events,
    revision: current.revision,
    signal: current.signal,
    connection: status.connection,
    error: status.error,
    refresh,
  };
}
