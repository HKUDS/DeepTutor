import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";
import type { ImportSource, NormalizedSession } from "@/lib/chat-import/types";
import type { SessionSummary } from "@/lib/session-api";

/** Per-session outcome echoed back by the import endpoint. */
export interface ImportSessionOutcome {
  external_id: string;
  session_id?: string;
  imported: boolean;
  reason?: string;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  sessions: ImportSessionOutcome[];
}

const IMPORTED_CACHE_PREFIX = "imported-sessions:";

export async function importChatHistory(
  source: ImportSource,
  sessions: NormalizedSession[],
  agent?: { id: string; name: string },
): Promise<ImportResult> {
  const response = await apiFetch(apiUrl("/api/v1/imports/chat-history"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source,
      sessions,
      agent_id: agent?.id ?? "",
      agent_name: agent?.name ?? "",
    }),
  });
  if (!response.ok) {
    throw new Error(`Import failed: ${response.status}`);
  }
  const data = (await response.json()) as ImportResult;
  invalidateClientCache(IMPORTED_CACHE_PREFIX);
  return data;
}

export async function listImportedSessions(
  limit = 200,
  offset = 0,
  options?: { force?: boolean },
): Promise<SessionSummary[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return withClientCache<SessionSummary[]>(
    `${IMPORTED_CACHE_PREFIX}${limit}:${offset}`,
    async () => {
      const response = await apiFetch(
        apiUrl(`/api/v1/imports/chat-history?${qs.toString()}`),
        { cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const data = (await response.json()) as { sessions: SessionSummary[] };
      return data.sessions ?? [];
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}
