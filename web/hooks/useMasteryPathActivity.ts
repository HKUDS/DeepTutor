"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchProgressEvents, type MasteryEvent } from "@/lib/learning-api";

/**
 * Follow a mastery path while it changes underneath you.
 *
 * Tutoring happens in the chat, usually in another tab, so a snapshot taken
 * when the dashboard opened goes stale within a turn. Every committed change
 * to a path already emits an event numbered by the path's revision, so this
 * polls for events *after* the last revision it saw: a quiet path costs one
 * indexed query returning nothing, and a busy one streams in order with no
 * gaps and no duplicates.
 *
 * `revision` is the single "the path moved" signal — render off the event list
 * and re-read anything else (the map, the summary list) when it changes.
 * Polling pauses while the tab is hidden and catches up the moment it is
 * visible again, so a backgrounded dashboard costs nothing.
 */
const DEFAULT_INTERVAL_MS = 4000;

export interface MasteryPathActivity {
  events: MasteryEvent[];
  revision: number;
  /** Poll now instead of waiting for the next tick. */
  refresh: () => void;
}

/** The feed is stamped with the path it belongs to, so switching paths shows
 *  nothing rather than the previous path's history for one render. */
export interface ActivityFeed {
  pathId: string | null;
  events: MasteryEvent[];
  revision: number;
}

export const EMPTY_FEED: ActivityFeed = {
  pathId: null,
  events: [],
  revision: 0,
};

/**
 * Fold one polled batch into the feed.
 *
 * `since` is what the request asked for, and it decides append vs replace: a
 * batch read from revision 0 is the path's whole history, so it *replaces*
 * rather than doubling anything already on screen. Keeping that rule here (and
 * not in the effect) is what makes a forced refresh safe to trigger from
 * anywhere.
 */
export function mergeEventBatch(
  previous: ActivityFeed,
  pathId: string,
  since: number,
  batch: MasteryEvent[],
): ActivityFeed {
  if (batch.length === 0) return previous;
  const continues = since > 0 && previous.pathId === pathId;
  return {
    pathId,
    events: continues ? [...previous.events, ...batch] : batch,
    revision: latestRevision(since, batch),
  };
}

/** Where the next read should start from after consuming ``batch``. */
export function latestRevision(since: number, batch: MasteryEvent[]): number {
  return batch.reduce(
    (highest, event) => Math.max(highest, event.revision),
    since,
  );
}

export function useMasteryPathActivity(
  pathId: string | null,
  options?: { intervalMs?: number },
): MasteryPathActivity {
  const intervalMs = options?.intervalMs ?? DEFAULT_INTERVAL_MS;
  const [feed, setFeed] = useState<ActivityFeed>(EMPTY_FEED);
  // The read cursor, carried in a ref so a tick never closes over a stale
  // revision and a new batch never restarts the polling effect. It is stamped
  // with its path, so a path switch reads from the beginning again without
  // anything having to reset it — and so a forced refresh resumes rather than
  // re-reading a history the feed already holds.
  const cursorRef = useRef<{ pathId: string | null; revision: number }>({
    pathId: null,
    revision: 0,
  });
  const [pollToken, setPollToken] = useState(0);

  const refresh = useCallback(() => setPollToken((token) => token + 1), []);

  useEffect(() => {
    if (!pathId) return;
    let cancelled = false;
    const controller = new AbortController();

    const poll = async () => {
      if (
        typeof document !== "undefined" &&
        document.visibilityState !== "visible"
      )
        return;
      const since =
        cursorRef.current.pathId === pathId ? cursorRef.current.revision : 0;
      try {
        const batch = await fetchProgressEvents(pathId, since, {
          signal: controller.signal,
        });
        if (cancelled || batch.length === 0) return;
        cursorRef.current = { pathId, revision: latestRevision(since, batch) };
        setFeed((previous) => mergeEventBatch(previous, pathId, since, batch));
      } catch {
        // A path can be deleted or reset mid-poll; the next tick recovers.
      }
    };

    void poll();
    const timer = setInterval(poll, intervalMs);
    // A hidden tab may have missed many ticks — catch up on return rather than
    // making the learner wait out a full interval.
    const pollWhenVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    window.addEventListener("focus", pollWhenVisible);
    document.addEventListener("visibilitychange", pollWhenVisible);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
      window.removeEventListener("focus", pollWhenVisible);
      document.removeEventListener("visibilitychange", pollWhenVisible);
    };
  }, [pathId, intervalMs, pollToken]);

  const current = feed.pathId === pathId ? feed : EMPTY_FEED;
  return { events: current.events, revision: current.revision, refresh };
}
