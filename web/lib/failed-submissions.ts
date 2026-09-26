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
  /** Legacy records had only a same-text baseline, which is not causal proof. */
  priorMatchingUserIds?: string[];
  /** The text survived, but its request context could not be stored. */
  retryRequiresReview?: boolean;
}

const STORAGE_KEY = "deeptutor.failedSubmissions";
const FALLBACK_KEY_PREFIX = `${STORAGE_KEY}.fallback.`;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function isRecord(value: unknown): value is FailedSubmissionRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<FailedSubmissionRecord>;
  return typeof record.content === "string" &&
    record.content.trim() !== "" &&
    Boolean(record.requestSnapshot) &&
    typeof record.savedAt === "number";
}

function asRecords(value: unknown): FailedSubmissionRecord[] {
  // Accept the single-record shape used before this fix.
  const records = isRecord(value) ? [value] :
    (Array.isArray(value) ? value.filter(isRecord) : []);
  // A pre-ID record has no causal server identity. Preserve its text and
  // require review before resend rather than matching another tab's row.
  return records.map((record) => record.submissionId
    ? record
    : { ...record, submissionId: `legacy:${record.savedAt}`, retryRequiresReview: true });
}

function readAll(): Record<string, FailedSubmissionRecord[]> {
  if (typeof window === "undefined") return {};
  try {
    const raw = browserStorage.readRaw("local", STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, FailedSubmissionRecord[]> = {};
    for (const [sessionId, value] of Object.entries(parsed)) {
      const records = asRecords(value);
      if (sessionId && records.length) out[sessionId] = records;
    }
    return out;
  } catch {
    return {};
  }
}

function fallbackKey(sessionId: string): string {
  return `${FALLBACK_KEY_PREFIX}${encodeURIComponent(sessionId)}`;
}

function writeAll(records: Record<string, FailedSubmissionRecord[]>): boolean {
  if (typeof window === "undefined") return false;
  return browserStorage.writeRaw("local", STORAGE_KEY, JSON.stringify(records));
}

/** A matching server-issued submission ID is the only proof of acceptance.
 * Another tab can submit the same text after this tab's last refresh. */
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

/** Preserve every pending message in a session, including successive failures. */
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
  const records = readAll();
  const now = Date.now();
  for (const [key, entries] of Object.entries(records)) {
    const fresh = entries.filter((record) => now - record.savedAt <= MAX_AGE_MS);
    if (fresh.length) records[key] = fresh;
    else delete records[key];
  }
  const current = readFailedSubmissions(sessionId);
  const next = current.filter((record) => record.submissionId !== submissionId);
  next.push({
    content: submission.content,
    capability: submission.capability ?? "",
    requestSnapshot: submission.requestSnapshot,
    savedAt: now,
    submissionId,
    priorMatchingUserIds: submission.priorMatchingUserIds ?? [],
  });
  records[sessionId] = next;
  if (writeAll(records)) {
    browserStorage.removeRaw("session", fallbackKey(sessionId));
    return submissionId;
  }
  // Large attachments may exhaust one storage area. Keep the complete
  // request in the other area before dropping to text-only snapshots.
  if (browserStorage.writeRaw("session", fallbackKey(sessionId), JSON.stringify(next))) {
    return submissionId;
  }
  const textOnly = next.map((record): FailedSubmissionRecord => {
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
  });
  if (browserStorage.writeRaw("session", fallbackKey(sessionId), JSON.stringify(textOnly))) {
    return submissionId;
  }
  // sessionStorage may be disabled even when a small localStorage write fits.
  records[sessionId] = textOnly;
  if (writeAll(records)) {
    browserStorage.removeRaw("session", fallbackKey(sessionId));
  }
  return submissionId;
}

export function readFailedSubmissions(sessionId: string): FailedSubmissionRecord[] {
  if (!sessionId) return [];
  const fallbackRaw = browserStorage.readRaw("session", fallbackKey(sessionId));
  let fallback: FailedSubmissionRecord[] = [];
  let fallbackValid = false;
  try {
    const parsed: unknown = fallbackRaw ? JSON.parse(fallbackRaw) : null;
    if (isRecord(parsed) || Array.isArray(parsed)) {
      fallback = asRecords(parsed);
      fallbackValid = true;
    }
  } catch {
    // An invalid fallback cannot suppress valid local records.
  }
  const records = fallbackValid ? fallback : (readAll()[sessionId] ?? []);
  const fresh = records.filter((record) => Date.now() - record.savedAt <= MAX_AGE_MS);
  if (fresh.length !== records.length) {
    if (!fresh.length) clearFailedSubmission(sessionId);
    else writeSessionRecords(sessionId, fresh);
  }
  return fresh;
}

/** Kept for callers interested in the most recent pending submission. */
export function readFailedSubmission(sessionId: string): FailedSubmissionRecord | null {
  return readFailedSubmissions(sessionId).at(-1) ?? null;
}

function writeSessionRecords(sessionId: string, entries: FailedSubmissionRecord[]): void {
  const records = readAll();
  if (entries.length) records[sessionId] = entries;
  else delete records[sessionId];
  if (writeAll(records)) {
    browserStorage.removeRaw("session", fallbackKey(sessionId));
  } else {
    // An empty array is a tombstone when a localStorage write cannot clear
    // its old record; the fallback must take precedence over that old data.
    browserStorage.writeRaw("session", fallbackKey(sessionId), JSON.stringify(entries));
  }
}

/** Clear only the submission the server acknowledged; older failures remain. */
export function clearFailedSubmission(sessionId: string, submissionId?: string): void {
  if (!sessionId) return;
  if (!submissionId) {
    writeSessionRecords(sessionId, []);
    return;
  }
  const current = readFailedSubmissions(sessionId);
  writeSessionRecords(sessionId, current.filter((record) => record.submissionId !== submissionId));
}
