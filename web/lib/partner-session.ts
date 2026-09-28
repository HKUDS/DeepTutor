/**
 * Per-partner web session key, persisted in localStorage so a refresh / tab
 * switch / navigation reattaches to the SAME conversation. The key is the
 * canonical session id the backend stores under (colon-free, so it doubles as
 * the filename stem and the id used by resume / delete / branch).
 */

import { browserStorage } from "@/shared/storage";

function storageKey(partnerId: string, accountId?: string | null): string {
  return accountId
    ? `partner-session:${accountId}:${partnerId}`
    : `partner-session:${partnerId}`;
}

/** Read without creating a key; callers decide whether an old key is owned by
 * the current account before migrating it. */
export function readPartnerSessionKey(
  partnerId: string,
  accountId: string,
): string | null {
  try {
    return browserStorage.readRaw("local", storageKey(partnerId, accountId)) || null;
  } catch {
    return null;
  }
}

export function readLegacyPartnerSessionKey(partnerId: string): string | null {
  try {
    return browserStorage.readRaw("local", storageKey(partnerId)) || null;
  } catch {
    return null;
  }
}

export async function initializePartnerSessionKey(
  partnerId: string,
  accountId: string | null,
  auth: { enabled: boolean; isAdmin: boolean; statusAvailable: boolean },
  listSessionKeys: () => Promise<string[]>,
): Promise<string> {
  if (!accountId) return freshPartnerSessionKey();
  const scoped = readPartnerSessionKey(partnerId, accountId);
  if (scoped) return scoped;

  let key: string | null = null;
  const legacy = readLegacyPartnerSessionKey(partnerId);
  if (legacy && auth.statusAvailable) {
    if (!auth.enabled && auth.isAdmin) {
      key = legacy;
    } else if (!auth.isAdmin) {
      const owned = await listSessionKeys().catch((): string[] => []);
      if (owned.includes(legacy)) key = legacy;
    }
  }
  key ||= freshPartnerSessionKey();
  persistPartnerSessionKey(partnerId, key, accountId);
  return key;
}

export function freshPartnerSessionKey(): string {
  return `web-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadPartnerSessionKey(
  partnerId: string,
  accountId?: string | null,
): string {
  try {
    const key = storageKey(partnerId, accountId);
    const existing = browserStorage.readRaw("local", key);
    if (existing) return existing;
    const fresh = freshPartnerSessionKey();
    browserStorage.writeRaw("local", key, fresh);
    return fresh;
  } catch {
    return freshPartnerSessionKey();
  }
}

export function persistPartnerSessionKey(
  partnerId: string,
  key: string,
  accountId?: string | null,
): void {
  try {
    browserStorage.writeRaw("local", storageKey(partnerId, accountId), key);
  } catch {
    /* private mode / storage disabled — in-memory only */
  }
}
