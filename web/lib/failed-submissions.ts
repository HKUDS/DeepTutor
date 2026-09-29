/** Locally persisted chat submissions whose acceptance has not been proved. */

import { browserStorage } from "@/shared/storage";
import { randomUuid } from "@/lib/random-uuid";

/** Kept opaque here so lib/ does not depend on features/. */
export type FailedSubmissionSnapshot = unknown;

export interface FailedSubmissionRecord {
  content: string;
  capability: string;
  requestSnapshot: FailedSubmissionSnapshot;
  savedAt: number;
  /** Also sent to the server and stored on its user row. */
  submissionId?: string;
  /** Present on records written by early versions of this feature. */
  priorMatchingUserIds?: string[];
  /** The text survived, but its request context could not be stored. */
  retryRequiresReview?: boolean;
}

const LEGACY_KEY = "deeptutor.failedSubmissions";
const LEGACY_FALLBACK_PREFIX = LEGACY_KEY + ".fallback.";
const RECORD_PREFIX = LEGACY_KEY + ".record.";
const TOMBSTONE_PREFIX = LEGACY_KEY + ".cleared.";
const BINDING_PREFIX = LEGACY_KEY + ".binding.";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function recordKey(sessionId: string, submissionId: string): string {
  return RECORD_PREFIX + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function recordPrefix(sessionId: string): string {
  return RECORD_PREFIX + encodeURIComponent(sessionId) + ":";
}

function tombstoneKey(sessionId: string, submissionId: string): string {
  return TOMBSTONE_PREFIX + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function tombstonePrefix(sessionId: string): string {
  return TOMBSTONE_PREFIX + encodeURIComponent(sessionId) + ":";
}

function bindingKey(sessionId: string, submissionId: string): string {
  return BINDING_PREFIX + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function bindingPrefix(sessionId: string): string {
  return BINDING_PREFIX + encodeURIComponent(sessionId) + ":";
}

function isRecord(value: unknown): value is FailedSubmissionRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<FailedSubmissionRecord>;
  return typeof record.content === "string" &&
    record.content.trim() !== "" &&
    Boolean(record.requestSnapshot) &&
    typeof record.savedAt === "number";
}

function asLegacyRecords(value: unknown): FailedSubmissionRecord[] {
  const records = isRecord(value) ? [value] :
    (Array.isArray(value) ? value.filter(isRecord) : []);
  // Records written before client_submission_id cannot be matched safely to
  // server rows. Keep their text, but require review before an automatic retry.
  return records.map((record) => record.submissionId
    ? record
    : { ...record, submissionId: "legacy:" + record.savedAt, retryRequiresReview: true });
}

function legacyRecords(sessionId: string): FailedSubmissionRecord[] {
  try {
    const raw = browserStorage.readRaw("local", LEGACY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [];
    return asLegacyRecords((parsed as Record<string, unknown>)[sessionId]);
  } catch {
    return [];
  }
}

function legacyRecordsForSession(sessionId: string): FailedSubmissionRecord[] {
  try {
    const raw = browserStorage.readRaw(
      "session", LEGACY_FALLBACK_PREFIX + encodeURIComponent(sessionId),
    );
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      // The old fallback, including an empty-array tombstone, took priority
      // over the shared map when the map could not be rewritten.
      if (isRecord(parsed) || Array.isArray(parsed)) return asLegacyRecords(parsed);
    }
  } catch {
    // A malformed or unavailable fallback cannot hide the local map.
  }
  return legacyRecords(sessionId);
}

function storedRecords(scope: "local" | "session", sessionId: string): FailedSubmissionRecord[] {
  return browserStorage.listRaw(scope, recordPrefix(sessionId)).flatMap(([key, raw]) => {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!isRecord(parsed) || !parsed.submissionId ||
          key !== recordKey(sessionId, parsed.submissionId)) return [];
      return [parsed];
    } catch {
      return [];
    }
  });
}

function clearedIds(sessionId: string): Map<string, number> {
  const ids = new Map<string, number>();
  for (const scope of ["local", "session"] as const) {
    for (const [key, raw] of browserStorage.listRaw(scope, tombstonePrefix(sessionId))) {
      const savedAt = Number(raw);
      if (!Number.isFinite(savedAt) || Date.now() - savedAt > MAX_AGE_MS) {
        browserStorage.removeRaw(scope, key);
        continue;
      }
      try {
        const id = decodeURIComponent(key.slice(tombstonePrefix(sessionId).length));
        ids.set(id, Math.max(ids.get(id) ?? 0, savedAt));
      } catch {
        // A malformed key cannot hide a valid submission.
      }
    }
  }
  return ids;
}

/** Only a matching server-side causal ID proves this submission was accepted. */
export function serverContainsFailedSubmission(
  messages: readonly {
    id?: number | string;
    role: string;
    content: string;
    metadata?: Record<string, unknown>;
  }[],
  record: FailedSubmissionRecord,
): boolean {
  return Boolean(record.submissionId) && messages.some(
    (message) => message.role === "user" &&
      message.metadata?.client_submission_id === record.submissionId,
  );
}

function textOnlyRecord(record: FailedSubmissionRecord): FailedSubmissionRecord {
  const snapshot = record.requestSnapshot as Record<string, unknown> | null;
  return {
    ...record,
    requestSnapshot: {
      content: record.content,
      capability: record.capability,
      language: typeof snapshot?.language === "string" ? snapshot.language : "en",
      enabledTools: [],
      knowledgeBases: [],
    },
    retryRequiresReview: true,
  };
}

type PersistedAs = "local_full" | "local_text" | "session_full" | "session_text";

function pruneExpiredEntries(): void {
  const now = Date.now();
  for (const scope of ["local", "session"] as const) {
    for (const [key, raw] of browserStorage.listRaw(scope, RECORD_PREFIX)) {
      let savedAt = Number.NaN;
      try {
        const value: unknown = JSON.parse(raw);
        if (isRecord(value)) savedAt = value.savedAt;
      } catch { /* malformed entries cannot be recovered */ }
      if (!Number.isFinite(savedAt) || now - savedAt > MAX_AGE_MS) {
        if (browserStorage.readRaw(scope, key) === raw) browserStorage.removeRaw(scope, key);
      }
    }
    for (const [key, raw] of browserStorage.listRaw(scope, TOMBSTONE_PREFIX)) {
      const savedAt = Number(raw);
      if (!Number.isFinite(savedAt) || now - savedAt > MAX_AGE_MS) {
        if (browserStorage.readRaw(scope, key) === raw) browserStorage.removeRaw(scope, key);
      }
    }
  }
}

function persistRecord(sessionId: string, record: FailedSubmissionRecord): PersistedAs | null {
  if (!record.submissionId) return null;
  const key = recordKey(sessionId, record.submissionId);
  const full = JSON.stringify(record);
  if (browserStorage.writeRaw("local", key, full)) {
    browserStorage.removeRaw("session", key);
    return "local_full";
  }
  // A week-old attachment in a different conversation can consume the entire
  // quota even though it is no longer recoverable. Free old per-record keys
  // before weakening this snapshot or giving up persistence.
  pruneExpiredEntries();
  if (browserStorage.writeRaw("local", key, full)) {
    browserStorage.removeRaw("session", key);
    return "local_full";
  }
  // Each submission has its own key. A large attachment or a concurrent tab
  // can never overwrite a different pending message's local record.
  const sessionFull = browserStorage.writeRaw("session", key, full);
  const textOnly = JSON.stringify(textOnlyRecord(record));
  if (browserStorage.writeRaw("local", key, textOnly)) {
    // Retain the full same-tab copy if it fits, so retry can keep attachments
    // while other tabs can at least recover the text and review the context.
    return "local_text";
  }
  if (sessionFull) return "session_full";
  if (browserStorage.writeRaw("session", key, textOnly)) return "session_text";
  return null;
}

interface DraftBinding {
  sourceKey: string;
  submissionId: string;
  targetSessionId: string;
  savedAt: number;
}

function readBindings(targetSessionId?: string): DraftBinding[] {
  return browserStorage.listRaw(
    "session", targetSessionId ? bindingPrefix(targetSessionId) : BINDING_PREFIX,
  ).flatMap(([key, raw]) => {
    try {
      const value = JSON.parse(raw) as Partial<DraftBinding>;
      if (!value.sourceKey || !value.submissionId || !value.targetSessionId ||
          typeof value.savedAt !== "number" ||
          key !== bindingKey(value.targetSessionId, value.submissionId)) return [];
      if (Date.now() - value.savedAt > MAX_AGE_MS) {
        browserStorage.removeRaw("session", key);
        return [];
      }
      return [value as DraftBinding];
    } catch {
      browserStorage.removeRaw("session", key);
      return [];
    }
  });
}

function directRecords(sessionId: string): FailedSubmissionRecord[] {
  const cleared = clearedIds(sessionId);
  const byId = new Map<string, FailedSubmissionRecord>();
  for (const record of [
    ...legacyRecordsForSession(sessionId),
    ...storedRecords("local", sessionId),
    ...storedRecords("session", sessionId),
  ]) {
    if (!record.submissionId ||
        record.savedAt <= (cleared.get(record.submissionId) ?? 0)) continue;
    if (Date.now() - record.savedAt > MAX_AGE_MS) continue;
    const previous = byId.get(record.submissionId);
    if (!previous || record.savedAt > previous.savedAt ||
        (record.savedAt === previous.savedAt &&
          !record.retryRequiresReview && previous.retryRequiresReview)) {
      byId.set(record.submissionId, record);
    }
  }
  return [...byId.values()];
}

export function storeFailedSubmission(
  sessionId: string,
  submission: {
    content: string;
    capability?: string | null;
    requestSnapshot: FailedSubmissionSnapshot;
    submissionId?: string;
    priorMatchingUserIds?: string[];
  },
): string | null {
  if (!sessionId || submission.content.trim() === "") return null;
  const submissionId = submission.submissionId ?? randomUuid();
  const record: FailedSubmissionRecord = {
    content: submission.content,
    capability: submission.capability ?? "",
    requestSnapshot: submission.requestSnapshot,
    // A stale tab can retry after another tab cleared this ID. Advance past
    // that tombstone even if both actions happen in the same clock tick.
    savedAt: Math.max(
      Date.now(), (clearedIds(sessionId).get(submissionId) ?? 0) + 1,
    ),
    submissionId,
    priorMatchingUserIds: submission.priorMatchingUserIds ?? [],
  };
  return persistRecord(sessionId, record) ? submissionId : null;
}

/** Read the union of shared local, this tab's fallback, and old formats. */
export function readFailedSubmissions(sessionId: string): FailedSubmissionRecord[] {
  if (!sessionId) return [];
  const byId = new Map<string, FailedSubmissionRecord>();
  const bindings = readBindings();
  const boundAwayIds = new Set(
    bindings.filter((binding) => binding.sourceKey === sessionId)
      .map((binding) => binding.submissionId),
  );
  for (const record of directRecords(sessionId)) {
    if (record.submissionId && !boundAwayIds.has(record.submissionId)) {
      byId.set(record.submissionId, record);
    }
  }
  for (const binding of bindings.filter((item) => item.targetSessionId === sessionId)) {
    const record = directRecords(binding.sourceKey)
      .find((item) => item.submissionId === binding.submissionId);
    if (!record?.submissionId) continue;
    const previous = byId.get(record.submissionId);
    if (!previous || record.savedAt > previous.savedAt ||
        (record.savedAt === previous.savedAt &&
          !record.retryRequiresReview && previous.retryRequiresReview)) {
      byId.set(record.submissionId, record);
    }
  }
  return [...byId.values()].sort((left, right) => left.savedAt - right.savedAt);
}

/** Kept for callers interested in the most recent pending submission. */
export function readFailedSubmission(sessionId: string): FailedSubmissionRecord | null {
  return readFailedSubmissions(sessionId).at(-1) ?? null;
}

/** A same-tab binding keeps the old durable draft visible in its server
 * session when a second full localStorage copy cannot fit. */
export function moveFailedSubmissions(
  sourceKey: string,
  sessionId: string,
  submissionIds: readonly string[],
): string[] {
  if (!sourceKey || !sessionId || sourceKey === sessionId || !submissionIds.length) return [];
  const ids = new Set(submissionIds);
  const visible: string[] = [];
  for (const record of readFailedSubmissions(sourceKey)) {
    if (!record.submissionId || !ids.has(record.submissionId)) continue;
    const persisted = persistRecord(sessionId, record);
    if (persisted === "local_full") {
      clearFailedSubmission(sourceKey, record.submissionId);
    } else {
      // Keep the source when the target is tab-scoped or text-only. A full
      // local source must survive closing this tab, and the binding lets this
      // tab recover it under the new server ID after refresh.
      const binding: DraftBinding = {
        sourceKey, submissionId: record.submissionId,
        targetSessionId: sessionId, savedAt: record.savedAt,
      };
      const bound = browserStorage.writeRaw(
        "session", bindingKey(sessionId, record.submissionId), JSON.stringify(binding),
      );
      if (!persisted && !bound) continue;
    }
    visible.push(record.submissionId);
  }
  return visible;
}

/** Remove one causal record without rewriting any other tab's pending data. */
export function clearFailedSubmission(sessionId: string, submissionId?: string): void {
  if (!sessionId) return;
  if (!submissionId) {
    for (const record of readFailedSubmissions(sessionId)) {
      if (record.submissionId) clearFailedSubmission(sessionId, record.submissionId);
    }
    return;
  }
  const binding = readBindings(sessionId)
    .find((item) => item.submissionId === submissionId);
  if (binding && binding.sourceKey !== sessionId) {
    clearFailedSubmission(binding.sourceKey, submissionId);
    browserStorage.removeRaw("session", bindingKey(sessionId, submissionId));
  }
  const key = recordKey(sessionId, submissionId);
  const marker = tombstoneKey(sessionId, submissionId);
  const recordAt = directRecords(sessionId)
    .find((record) => record.submissionId === submissionId)?.savedAt ?? 0;
  const clearedAt = clearedIds(sessionId).get(submissionId) ?? 0;
  const markerAt = Math.max(Date.now(), recordAt + 1, clearedAt + 1);
  let marked = browserStorage.writeRaw("local", marker, String(markerAt));
  browserStorage.removeRaw("local", key);
  browserStorage.removeRaw("session", key);
  if (!marked) marked = browserStorage.writeRaw("local", marker, String(markerAt));
  if (!marked) browserStorage.writeRaw("session", marker, String(markerAt));
}
