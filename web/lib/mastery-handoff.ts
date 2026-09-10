import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultPayload } from "@/lib/tool-event";

/**
 * Reading the mastery navigation tools' hand-off signals off a turn's stream.
 *
 * Chat can address the learner's mastery topics but never teaches them: the
 * study screen owns the map, the lesson outline and the gate, so a request
 * like "take me back through lesson one" is resolved here and *handed over*
 * rather than answered in place. `mastery_open_session` and
 * `mastery_new_session` (see `deeptutor/tools/mastery_nav.py`) emit that
 * hand-off as `mastery_handoff` on a tool result's metadata, and it becomes a
 * card.
 *
 * A card rather than an automatic redirect, for the same reason Course Study
 * uses one (`lib/course-handoff.ts`): a page that changes underneath the
 * learner reads as a malfunction, and the opening line is a proposal they
 * should be able to edit or ignore.
 *
 * Kept as pure functions apart from the component that renders them, so the
 * parsing can be tested without a DOM.
 */

/** Whether the card resumes a conversation or starts one. */
export type MasteryHandoffKind = "open" | "new";

export interface MasteryHandoffPayload {
  kind: MasteryHandoffKind;
  path_id: string;
  path_name: string;
  /** Topic emoji, or "" when the topic has none. */
  emoji: string;
  /** Empty for `kind: "new"`. */
  session_id: string;
  session_title: string;
  session_messages: number;
  /** Epoch seconds; 0 when unknown or for `kind: "new"`. */
  session_updated_at: number;
  /** A mastery question is open in that conversation. */
  session_awaiting: boolean;
  /** The tutor is mid-answer in that conversation. */
  session_running: boolean;
  /** The lesson the learner named, validated server-side. May be empty. */
  module_id: string;
  module_name: string;
  /** The first message the destination opens with. May be empty. */
  opening_message: string;
  /** Why this is worth doing now — the card's headline. May be empty. */
  reason: string;
  due_reviews: number;
  mastered: number;
  objectives: number;
}

function isKind(value: unknown): value is MasteryHandoffKind {
  return value === "open" || value === "new";
}

function count(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
}

/**
 * Extract a hand-off from one stream event, or null.
 *
 * The dispatcher nests a tool's own `ToolResult.metadata` under
 * `tool_metadata` (`core/agentic/tool_dispatch.py`), so reading only the top
 * level type-checks fine and silently finds nothing. The top level is still
 * checked as a fallback for callers that emit the event directly.
 */
export function masteryHandoffFrom(event: {
  type?: string;
  metadata?: unknown;
}): MasteryHandoffPayload | null {
  if (event?.type !== "tool_result") return null;
  const metadata = event.metadata;
  if (!metadata || typeof metadata !== "object") return null;

  const raw = toolResultPayload(metadata, "mastery_handoff");
  if (!raw || typeof raw !== "object") return null;
  const payload = raw as Record<string, unknown>;
  if (!isKind(payload.kind)) return null;
  const pathId = String(payload.path_id ?? "").trim();
  if (!pathId) return null;
  const sessionId = String(payload.session_id ?? "").trim();
  // A card that resumes nothing in particular would land on the topic's
  // draft route and quietly start a *new* conversation instead — the opposite
  // of what "take me back to where I was" asked for.
  if (payload.kind === "open" && !sessionId) return null;

  return {
    kind: payload.kind,
    path_id: pathId,
    path_name: String(payload.path_name ?? "").trim(),
    emoji: String(payload.emoji ?? "").trim(),
    session_id: sessionId,
    session_title: String(payload.session_title ?? "").trim(),
    session_messages: count(payload.session_messages),
    session_updated_at: count(payload.session_updated_at),
    session_awaiting: Boolean(payload.session_awaiting),
    session_running: Boolean(payload.session_running),
    module_id: String(payload.module_id ?? "").trim(),
    module_name: String(payload.module_name ?? "").trim(),
    opening_message: String(payload.opening_message ?? "").trim(),
    reason: String(payload.reason ?? "").trim(),
    due_reviews: count(payload.due_reviews),
    mastered: count(payload.mastered),
    objectives: count(payload.objectives),
  };
}

/**
 * Every hand-off in a message, de-duplicated by destination.
 *
 * A turn may legitimately offer two ("finish lesson 2, or review lesson 1
 * first"), so all of them are kept — but a model that calls the tool twice
 * for one destination should still produce one card.
 */
export function extractMasteryHandoffs(
  events: StreamEvent[] | undefined,
): MasteryHandoffPayload[] {
  if (!events || events.length === 0) return [];
  const seen = new Set<string>();
  const handoffs: MasteryHandoffPayload[] = [];
  for (const event of events) {
    const payload = masteryHandoffFrom(event);
    if (!payload) continue;
    const key = `${payload.kind}:${payload.path_id}:${payload.session_id}:${payload.module_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    handoffs.push(payload);
  }
  return handoffs;
}

/**
 * Resolve a hand-off to an in-app route.
 *
 * `/mastery/<id>/sessions` is the draft route: arriving there starts a new
 * conversation on that topic, which is exactly what `kind: "new"` means. The
 * ids are percent-encoded rather than trusted — they reached us through a
 * model, and a path segment is the one place a stray slash would change which
 * page opens.
 */
export function masteryHandoffHref(payload: MasteryHandoffPayload): string {
  const path = encodeURIComponent(payload.path_id);
  return payload.kind === "open"
    ? `/mastery/${path}/sessions/${encodeURIComponent(payload.session_id)}`
    : `/mastery/${path}/sessions`;
}
