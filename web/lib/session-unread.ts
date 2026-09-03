"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Which finished sessions the reader has not looked at yet.
 *
 * Deliberately in-memory and scoped to one sitting, not persisted. The signal
 * is "this finished while you were somewhere else" — persisting it would
 * light up every historical session on the next cold load, which is the
 * opposite of useful.
 *
 * Module-level rather than React state because the sidebar unmounts and
 * remounts as the reader moves between surfaces, and a mark that forgets
 * itself on navigation would never survive long enough to be seen.
 */
const unread = new Set<string>();

/**
 * The live set as of the previous reconcile, so a *transition* out of it can
 * be detected. `null` until the first call — the first list seen establishes
 * a baseline rather than reporting everything in it as a change.
 */
let lastLive: ReadonlySet<string> | null = null;

const listeners = new Set<() => void>();

/**
 * `useSyncExternalStore` compares snapshots by identity, so each change has
 * to publish a new object — the live `Set` is mutated in place and would
 * always look unchanged.
 */
let snapshot: ReadonlySet<string> = new Set();

const EMPTY: ReadonlySet<string> = new Set();

function emit(): void {
  snapshot = new Set(unread);
  for (const listener of listeners) listener();
}

/**
 * Fold the current set of running sessions into the unread set.
 *
 * Takes the live set rather than session records with a `status` field, for
 * two reasons. It is the honest signal — the runtime map behind it holds
 * running sessions *only*, so dropping out of it is exactly "this finished",
 * whereas a stored `status` can read `running` for a session whose turn died
 * long ago. And it needs no per-session bookkeeping: one set difference finds
 * everything that just finished.
 *
 * The first call only establishes a baseline. A session already finished when
 * first seen is not unread — the reader was never shown it change, so
 * flagging it would just mean "you have old sessions". Opening a session
 * clears its flag.
 */
export function reconcileUnread(
  liveSessionIds: ReadonlySet<string>,
  activeSessionId: string | null,
): void {
  let changed = false;

  if (lastLive) {
    for (const id of lastLive) {
      if (liveSessionIds.has(id)) continue;
      if (id === activeSessionId) continue;
      if (unread.has(id)) continue;
      unread.add(id);
      changed = true;
    }
  }
  lastLive = new Set(liveSessionIds);

  // Looking at a session is what marks it read.
  if (activeSessionId && unread.delete(activeSessionId)) changed = true;

  if (changed) emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The set of sessions that finished while the reader was elsewhere. */
export function useUnreadSessions(): ReadonlySet<string> {
  const getSnapshot = useCallback(() => snapshot, []);
  const getServerSnapshot = useCallback(() => EMPTY, []);
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
