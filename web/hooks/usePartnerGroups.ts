"use client";

import { useEffect, useSyncExternalStore } from "react";
import { listPartnerGroups, type PartnerGroup } from "@/lib/partner-groups-api";

/**
 * The partner groups this account can convene, held once for the whole app —
 * the composer's partner menu and the selection menu's "ask a group" read the
 * same list. Same policy as ``usePartnerRoster``: refreshed on window focus,
 * at most once per ``STALE_MS``, an in-flight fetch joined rather than repeated.
 */
interface GroupList {
  groups: PartnerGroup[];
  loading: boolean;
  error: boolean;
}

const STALE_MS = 30_000;
const EMPTY: GroupList = { groups: [], loading: false, error: false };

let current: GroupList = EMPTY;
let loadedAt = 0;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function publish(next: GroupList) {
  current = next;
  for (const listener of listeners) listener();
}

export function refreshPartnerGroups(force = false): Promise<void> {
  if (inflight) return inflight;
  if (!force && loadedAt && Date.now() - loadedAt < STALE_MS)
    return Promise.resolve();
  publish({ ...current, loading: true });
  inflight = listPartnerGroups()
    .then((groups) => {
      loadedAt = Date.now();
      publish({ groups, loading: false, error: false });
    })
    .catch(() => publish({ ...current, loading: false, error: true }))
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePartnerGroups(enabled = true): GroupList {
  const value = useSyncExternalStore(
    subscribe,
    () => current,
    () => EMPTY,
  );
  useEffect(() => {
    if (!enabled) return;
    void refreshPartnerGroups();
    const onFocus = () => void refreshPartnerGroups();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled]);
  return enabled ? value : EMPTY;
}
