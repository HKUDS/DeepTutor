import type { StreamEvent } from "@/features/chat/model/protocol";
import type { LectureChange } from "@/lib/learning-api";
import { toolResultPayload } from "@/lib/tool-event";

/** The unconfirmed revision a reply proposed, and where it lives. */
export interface LectureRevisionPreview {
  previewId: number;
  sessionId: string;
  baseRevision: number;
  changes: LectureChange[];
}

export interface LectureChangeLike {
  op?: string;
  heading?: string;
  before?: string;
  after?: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function changes(value: unknown): LectureChange[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => asRecord(entry))
    .filter((entry): entry is Record<string, unknown> => entry !== null)
    .map((entry) => ({
      op: normalizeOp(entry.op),
      heading: typeof entry.heading === "string" ? entry.heading : "",
      before: typeof entry.before === "string" ? entry.before : "",
      after: typeof entry.after === "string" ? entry.after : "",
    }));
}

function normalizeOp(value: unknown): LectureChange["op"] {
  return value === "added" || value === "removed" || value === "replaced" ? value : "replaced";
}

/**
 * The lecture revision a reply proposed, if it proposed one.
 *
 * Previews are one-shot: only the newest uncommitted one in a message is
 * worth a card, because a learner reading three of them has to guess which
 * applies to the text in front of them.
 */
export function lectureRevisionOnMessage(
  events: StreamEvent[] | undefined,
): LectureRevisionPreview | null {
  let found: LectureRevisionPreview | null = null;
  for (const event of events || []) {
    if (event.type !== "tool_result") continue;
    const raw = asRecord(toolResultPayload(event.metadata, "mastery_lecture_preview"));
    if (!raw || raw.status !== "preview_only_not_saved") continue;
    const previewId = Number(raw.preview_id);
    if (!Number.isFinite(previewId) || previewId <= 0) continue;
    found = {
      previewId,
      sessionId: typeof raw.session_id === "string" ? raw.session_id : "",
      baseRevision: Number(raw.base_revision) || 0,
      changes: changes(raw.changes),
    };
  }
  return found;
}
