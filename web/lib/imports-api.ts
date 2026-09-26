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
  if (sessions.length === 0) {
    throw new Error("No sessions to import");
  }
  const response = await apiFetch(apiUrl("/api/imports/chat-history"), {
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

/**
 * Upload a large static export without crossing the backend's per-request
 * session ceiling. Re-imports are idempotent, so a retry after a partial
 * network failure safely skips batches that already landed.
 */
export async function importChatHistoryInBatches(
  source: ImportSource,
  sessions: NormalizedSession[],
  options?: {
    batchSize?: number;
    onProgress?: (done: number, total: number) => void;
  },
): Promise<ImportResult> {
  if (sessions.length === 0) throw new Error("No sessions to import");
  const batchSize = Math.max(1, Math.min(1000, options?.batchSize ?? 100));
  const combined: ImportResult = { imported: 0, skipped: 0, sessions: [] };
  for (let start = 0; start < sessions.length; start += batchSize) {
    const batch = sessions.slice(start, start + batchSize);
    const result = await importChatHistory(source, batch);
    combined.imported += result.imported;
    combined.skipped += result.skipped;
    combined.sessions.push(...result.sessions);
    options?.onProgress?.(
      Math.min(start + batch.length, sessions.length),
      sessions.length,
    );
  }
  return combined;
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
        apiUrl(`/api/imports/chat-history?${qs.toString()}`),
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
