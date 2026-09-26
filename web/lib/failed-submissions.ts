/**
 * Locally persisted failed chat submissions (issue #1594).
 *
 * When a submission never reaches the server (the WebSocket could not
 * connect), the optimistic user row exists only in memory — a reload wiped
 * both the text and any sign it failed. These helpers keep the last failed
 * submission of each session in local storage so the transcript can be
 * reopened with the text recoverable and marked unsent.
 *
 * A record is written pessimistically when a fresh turn is submitted, and
 * removed by any evidence the server took the turn over (a terminal event,
 * ``done``, or a user cancel). Whatever survives is therefore a submission
 * the client cannot prove the server ever accepted.
 */

import { browserStorage } from "@/shared/storage";

/** The request snapshot replayed by the resend path. Opaque here on
 *  purpose: at runtime it is a full ``MessageRequestSnapshot``, but typing
 *  it would point ``lib/`` at ``features/``. The chat adapter casts it
 *  back on the way out. */
export type FailedSubmissionSnapshot = unknown;

export interface FailedSubmissionRecord {
  content: string;
  capability: string;
  requestSnapshot: FailedSubmissionSnapshot;
  savedAt: number;
  /** Server user rows with this text before this submission was attempted. */
  priorMatchingUserIds?: string[];
  /** The text survived, but its request context could not be stored. */
  retryRequiresReview?: boolean;
}

const STORAGE_KEY = "deeptutor.failedSubmissions";
const FALLBACK_KEY_PREFIX = `${STORAGE_KEY}.fallback.`;
/** Records older than this are stale transcript history, not a pending retry. */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function isRecord(value: unknown): value is FailedSubmissionRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<FailedSubmissionRecord>;
  return (
    typeof record.content === "string" &&
    record.content.trim() !== "" &&
    Boolean(record.requestSnapshot) &&
    typeof record.savedAt === "number"
  );
}

function readAll(): Record<string, FailedSubmissionRecord> {
  if (typeof window === "undefined") return {};
  try {
    const raw = browserStorage.readRaw("local", STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const out: Record<string, FailedSubmissionRecord> = {};
    for (const [sessionId, value] of Object.entries(
      parsed as Record<string, unknown>,
    )) {
      if (sessionId && isRecord(value)) out[sessionId] = value;
    }
    return out;
  } catch {
    return {};
  }
}

function fallbackKey(sessionId: string): string {
  return `${FALLBACK_KEY_PREFIX}${encodeURIComponent(sessionId)}`;
}

function writeAll(records: Record<string, FailedSubmissionRecord>): boolean {
  if (typeof window === "undefined") return false;
  return browserStorage.writeRaw("local", STORAGE_KEY, JSON.stringify(records));
}

/** Only a *new* server row proves this submission was accepted. Earlier turns
 * can have identical text, so comparing the last user's content is unsafe. */
export function serverContainsFailedSubmission(
  messages: readonly { id?: number | string; role: string; content: string }[],
  record: FailedSubmissionRecord,
): boolean {
  if (!record.priorMatchingUserIds) return false;
  const prior = new Set(record.priorMatchingUserIds);
  return messages.some(
    (message) =>
      message.role === "user" &&
      message.content === record.content &&
      message.id != null &&
      !prior.has(String(message.id)),
  );
}

/** Remember ``submission`` as the latest unproven submission of a session. */
export function storeFailedSubmission(
  sessionId: string,
  submission: {
    content: string;
    capability?: string | null;
    requestSnapshot: FailedSubmissionSnapshot;
    priorMatchingUserIds?: string[];
  },
): void {
  if (!sessionId || submission.content.trim() === "") return;
  const records = readAll();
  const now = Date.now();
  for (const [key, record] of Object.entries(records)) {
    if (now - record.savedAt > MAX_AGE_MS) delete records[key];
  }
  records[sessionId] = {
    content: submission.content,
    capability: submission.capability ?? "",
    requestSnapshot: submission.requestSnapshot,
    savedAt: now,
    priorMatchingUserIds: submission.priorMatchingUserIds ?? [],
  };
  if (writeAll(records)) {
    browserStorage.removeRaw("session", fallbackKey(sessionId));
    return;
  }
  // A base64 attachment can exceed localStorage's quota. sessionStorage is
  // independent and survives a reload in this tab, so try the full request
  // there before falling back to the text alone.
  const fullRecord = records[sessionId];
  if (browserStorage.writeRaw("session", fallbackKey(sessionId), JSON.stringify(fullRecord))) {
    return;
  }
  const snapshot = fullRecord.requestSnapshot as Record<string, unknown> | null;
  const textOnly: FailedSubmissionRecord = {
    ...fullRecord,
    requestSnapshot: {
      content: fullRecord.content,
      capability: fullRecord.capability,
      language: typeof snapshot?.language === "string" ? snapshot.language : "en",
      enabledTools: [],
      knowledgeBases: [],
    },
    retryRequiresReview: true,
  };
  browserStorage.writeRaw("session", fallbackKey(sessionId), JSON.stringify(textOnly));
}

/** The session's unproven submission, if one survived. */
export function readFailedSubmission(
  sessionId: string,
): FailedSubmissionRecord | null {
  if (!sessionId) return null;
  const fallbackRaw = browserStorage.readRaw("session", fallbackKey(sessionId));
  let fallback: FailedSubmissionRecord | null = null;
  try {
    const parsed: unknown = fallbackRaw ? JSON.parse(fallbackRaw) : null;
    if (isRecord(parsed)) fallback = parsed;
  } catch {
    // An invalid fallback cannot suppress a valid local record.
  }
  const record = fallback ?? readAll()[sessionId];
  if (!record) return null;
  if (Date.now() - record.savedAt > MAX_AGE_MS) {
    clearFailedSubmission(sessionId);
    return null;
  }
  return record;
}

/** Drop the session's record — used once the server is known to own the turn. */
export function clearFailedSubmission(sessionId: string): void {
  if (!sessionId) return;
  browserStorage.removeRaw("session", fallbackKey(sessionId));
  const records = readAll();
  if (!(sessionId in records)) return;
  delete records[sessionId];
  if (!writeAll(records)) browserStorage.removeRaw("local", STORAGE_KEY);
}
