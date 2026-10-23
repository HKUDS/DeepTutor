/** Locally persisted chat submissions whose acceptance has not been proved. */

import { browserStorage } from "@/shared/storage";
import { randomUuid } from "@/lib/random-uuid";
import { recoveryPrincipal } from "@/lib/recovery-principal";

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

const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function ownerPrefix(kind: "record" | "cleared" | "binding"): string {
  const principal = recoveryPrincipal();
  if (principal === null) throw new Error("Recovery ownership is unresolved");
  return "deeptutor.failedSubmissions.owner." + encodeURIComponent(principal) + "." + kind + ".";
}

function recordKey(sessionId: string, submissionId: string): string {
  return ownerPrefix("record") + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function recordPrefix(sessionId: string): string {
  return ownerPrefix("record") + encodeURIComponent(sessionId) + ":";
}

function tombstoneKey(sessionId: string, submissionId: string): string {
  return ownerPrefix("cleared") + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function tombstonePrefix(sessionId: string): string {
  return ownerPrefix("cleared") + encodeURIComponent(sessionId) + ":";
}

function bindingKey(sessionId: string, submissionId: string): string {
  return ownerPrefix("binding") + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(submissionId);
}

function bindingPrefix(sessionId: string): string {
  return ownerPrefix("binding") + encodeURIComponent(sessionId) + ":";
}

function hasSubmissionPayload(content: string, snapshot: unknown): boolean {
  if (content.trim()) return true;
  if (!snapshot || typeof snapshot !== "object") return false;
  const attachments = (snapshot as Record<string, unknown>).attachments;
  return Array.isArray(attachments) && attachments.length > 0;
}

function isRecord(value: unknown): value is FailedSubmissionRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<FailedSubmissionRecord>;
  return typeof record.content === "string" &&
    hasSubmissionPayload(record.content, record.requestSnapshot) &&
    Boolean(record.requestSnapshot) &&
    typeof record.savedAt === "number";
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
  record: Pick<FailedSubmissionRecord, "submissionId">,
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
    for (const [key, raw] of browserStorage.listRaw(scope, ownerPrefix("record"))) {
      let savedAt = Number.NaN;
      try {
        const value: unknown = JSON.parse(raw);
        if (isRecord(value)) savedAt = value.savedAt;
      } catch { /* malformed entries cannot be recovered */ }
      if (!Number.isFinite(savedAt) || now - savedAt > MAX_AGE_MS) {
        if (browserStorage.readRaw(scope, key) === raw) browserStorage.removeRaw(scope, key);
      }
    }
    for (const [key, raw] of browserStorage.listRaw(scope, ownerPrefix("cleared"))) {
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
  // A media-only submission has no useful text fallback. Never report an
  // empty, attachment-free record as safely recoverable (#1793).
  if (!record.content.trim()) return sessionFull ? "session_full" : null;
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
    "session", targetSessionId ? bindingPrefix(targetSessionId) : ownerPrefix("binding"),
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
  if (recoveryPrincipal() === null || !sessionId || !hasSubmissionPayload(submission.content, submission.requestSnapshot)) return null;
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

/** Read this owner's local and tab fallback records. Unowned legacy data is
 * preserved in storage, never silently attributed to the current account. */
export function readFailedSubmissions(sessionId: string, includeSuperseded = false): FailedSubmissionRecord[] {
  if (recoveryPrincipal() === null || !sessionId) return [];
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
  const records = [...byId.values()];
  const replacedIds = new Set(records.flatMap((record) => {
    const snapshot = record.requestSnapshot as { replacesSubmissionId?: string } | null;
    return snapshot?.replacesSubmissionId ? [snapshot.replacesSubmissionId] : [];
  }));
  return records.filter((record) => includeSuperseded || !replacedIds.has(record.submissionId!))
    .sort((left, right) => left.savedAt - right.savedAt);
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
  if (recoveryPrincipal() === null || !sourceKey || !sessionId || sourceKey === sessionId || !submissionIds.length) return [];
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

/** Remove one causal record; return whether its retirement was recorded. */
export function clearFailedSubmission(sessionId: string, submissionId?: string): boolean {
  if (recoveryPrincipal() === null || !sessionId) return false;
  if (!submissionId) {
    let cleared = true;
    for (const record of readFailedSubmissions(sessionId)) {
      if (record.submissionId && !clearFailedSubmission(sessionId, record.submissionId)) cleared = false;
    }
    return cleared;
  }
  const binding = readBindings(sessionId)
    .find((item) => item.submissionId === submissionId);
  const sourceRecordAt = binding ? directRecords(binding.sourceKey)
    .find((item) => item.submissionId === submissionId)?.savedAt ?? 0 : 0;
  const key = recordKey(sessionId, submissionId);
  const marker = tombstoneKey(sessionId, submissionId);
  const recordAt = directRecords(sessionId)
    .find((record) => record.submissionId === submissionId)?.savedAt ?? 0;
  const clearedAt = clearedIds(sessionId).get(submissionId) ?? 0;
  const markerAt = Math.max(Date.now(), recordAt + 1, clearedAt + 1);
  let marked = browserStorage.writeRaw("local", marker, String(markerAt));
  if (!marked) marked = browserStorage.writeRaw("session", marker, String(markerAt));
  // Do not destroy the only recovery copy if its retirement cannot be saved.
  if (!marked) return false;
  const advanced = () => {
    const current = directRecords(sessionId).find((item) => item.submissionId === submissionId);
    const currentBinding = readBindings(sessionId).find((item) => item.submissionId === submissionId);
    return (current?.savedAt ?? 0) > recordAt ||
      currentBinding?.sourceKey !== binding?.sourceKey ||
      currentBinding?.savedAt !== binding?.savedAt ||
      Boolean(binding && (directRecords(binding.sourceKey)
        .find((item) => item.submissionId === submissionId)?.savedAt ?? 0) > sourceRecordAt);
  };
  // A stale tab can retry this ID after the marker. Preserve advancement we
  // can observe; browser storage does not offer atomic cross-tab compare/delete.
  if (advanced()) return false;
  if (binding && binding.sourceKey !== sessionId) {
    if (!clearFailedSubmission(binding.sourceKey, submissionId)) return false;
    browserStorage.removeRaw("session", bindingKey(sessionId, submissionId));
  }
  const current = directRecords(sessionId).find((item) => item.submissionId === submissionId);
  if ((current?.savedAt ?? 0) > recordAt) return false;
  browserStorage.removeRaw("local", key);
  browserStorage.removeRaw("session", key);
  return true;
}
