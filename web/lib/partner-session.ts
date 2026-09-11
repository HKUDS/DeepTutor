/**
 * Per-partner web session key, persisted in localStorage so a refresh / tab
 * switch / navigation reattaches to the SAME conversation. The key is the
 * canonical session id the backend stores under (colon-free, so it doubles as
 * the filename stem and the id used by resume / delete / branch).
 */

import { browserStorage } from "@/shared/storage";

function storageKey(partnerId: string): string {
  return `partner-session:${partnerId}`;
}

export function freshPartnerSessionKey(): string {
  return `web-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadPartnerSessionKey(partnerId: string): string {
  try {
    const existing = browserStorage.readRaw("local", storageKey(partnerId));
    if (existing) return existing;
    const fresh = freshPartnerSessionKey();
    browserStorage.writeRaw("local", storageKey(partnerId), fresh);
    return fresh;
  } catch {
    return freshPartnerSessionKey();
  }
}

export function persistPartnerSessionKey(partnerId: string, key: string): void {
  try {
    browserStorage.writeRaw("local", storageKey(partnerId), key);
  } catch {
    /* private mode / storage disabled — in-memory only */
  }
}
