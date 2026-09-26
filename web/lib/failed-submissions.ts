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
}

const STORAGE_KEY = "deeptutor.failedSubmissions";
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

function writeAll(records: Record<string, FailedSubmissionRecord>): void {
  if (typeof window === "undefined") return;
  // A full or unavailable store just means no recovery after reload;
  // the in-session retry still works.
  browserStorage.writeRaw("local", STORAGE_KEY, JSON.stringify(records));
}

/** Remember ``submission`` as the latest unproven submission of a session. */
export function storeFailedSubmission(
  sessionId: string,
  submission: {
    content: string;
    capability?: string | null;
    requestSnapshot: FailedSubmissionSnapshot;
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
  };
  writeAll(records);
}

/** The session's unproven submission, if one survived. */
export function readFailedSubmission(
  sessionId: string,
): FailedSubmissionRecord | null {
  if (!sessionId) return null;
  const record = readAll()[sessionId];
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
  const records = readAll();
  if (!(sessionId in records)) return;
  delete records[sessionId];
  writeAll(records);
}
