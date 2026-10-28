"use client";

import { useEffect, useSyncExternalStore } from "react";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";

/**
 * The partners this account can talk to, held once for the whole app.
 *
 * The composer's menus and every transcript line that names a partner read
 * the same list, so it is fetched once and shared rather than per consumer.
 * It refreshes when the window regains focus — a partner made or renamed in
 * another tab shows up — but no more than once per `STALE_MS`, and a fetch
 * already in flight is joined, not repeated. Nothing is kept beyond the one
 * list.
 */
interface Roster {
  partners: PartnerInfo[];
  loading: boolean;
  error: boolean;
}

const STALE_MS = 30_000;

let roster: Roster = { partners: [], loading: false, error: false };
let loadedAt = 0;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function publish(next: Roster) {
  roster = next;
  for (const listener of listeners) listener();
}

/** Fetch the list unless a fresh one is held or one is already on its way. */
export function refreshPartnerRoster(force = false): Promise<void> {
  if (inflight) return inflight;
  if (!force && loadedAt && Date.now() - loadedAt < STALE_MS) return Promise.resolve();
  publish({ ...roster, loading: true });
  inflight = listPartners()
    .then((partners) => {
      loadedAt = Date.now();
      publish({ partners, loading: false, error: false });
    })
    .catch(() => publish({ ...roster, loading: false, error: true }))
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: Roster = { partners: [], loading: false, error: false };

export function usePartnerRoster(enabled = true): Roster {
  const value = useSyncExternalStore(subscribe, () => roster, () => EMPTY);
  useEffect(() => {
    if (!enabled) return;
    void refreshPartnerRoster();
    const onFocus = () => void refreshPartnerRoster();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled]);
  return enabled ? value : EMPTY;
}

/** One partner by id, from the shared list; undefined until it has loaded. */
export function usePartner(partnerId: string | null | undefined): PartnerInfo | undefined {
  const { partners } = usePartnerRoster(Boolean(partnerId));
  return partnerId ? partners.find((partner) => partner.partner_id === partnerId) : undefined;
}
