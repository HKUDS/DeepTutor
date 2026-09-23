/**
 * Per-partner web session key, persisted in localStorage so a refresh / tab
 * switch / navigation reattaches to the SAME conversation. The key is the
 * canonical session id the backend stores under (colon-free, so it doubles as
 * the filename stem and the id used by resume / delete / branch).
 */

import { apiFetch, apiUrl } from "@/lib/api";
import { browserStorage } from "@/shared/storage";

export type PartnerSessionRoaming = {
  enabled: boolean;
  session_key: string;
};

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

async function roamingResponse(
  response: Response,
): Promise<PartnerSessionRoaming> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Partner session setting failed: HTTP ${response.status}`,
    );
  }
  return response.json();
}

export async function getPartnerSessionRoaming(
  partnerId: string,
): Promise<PartnerSessionRoaming> {
  return roamingResponse(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/session-roaming`,
      ),
      { cache: "no-store" },
    ),
  );
}

export async function updatePartnerSessionRoaming(
  partnerId: string,
  enabled: boolean,
  sessionKey?: string,
): Promise<PartnerSessionRoaming> {
  return roamingResponse(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/session-roaming`,
      ),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          ...(sessionKey ? { session_key: sessionKey } : {}),
        }),
      },
    ),
  );
}
