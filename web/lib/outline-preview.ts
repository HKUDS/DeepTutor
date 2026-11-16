import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultPayload } from "@/lib/tool-event";

export interface OutlinePreview {
  previewId: number;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** The unsaved outline revision a reply proposed, if it proposed one. */
export function outlinePreviewOnMessage(events: StreamEvent[] | undefined): OutlinePreview | null {
  for (const event of events || []) {
    if (event.type !== "tool_result") continue;
    const raw = asRecord(toolResultPayload(event.metadata, "mastery_revision_preview"));
    if (!raw || raw.status !== "preview_only_not_saved") continue;
    const previewId = Number(raw.preview_id);
    if (!Number.isInteger(previewId) || previewId < 1) continue;
    return { previewId };
  }
  return null;
}

export function modeHandoffSession(events: StreamEvent[] | undefined): string {
  let sessionId = "";
  for (const event of events || []) {
    if (event.type !== "tool_result") continue;
    const raw = asRecord(toolResultPayload(event.metadata, "mastery_mode"));
    const next = typeof raw?.session_id === "string" ? raw.session_id.trim() : "";
    if (raw?.status === "open_session" && next) sessionId = next;
  }
  return sessionId;
}

/** The knowledge point an ``open_session`` handoff opened, if it named one. */
export function modeHandoffKnowledgePoint(
  events: StreamEvent[] | undefined,
): string {
  let pointId = "";
  for (const event of events || []) {
    if (event.type !== "tool_result") continue;
    const raw = asRecord(toolResultPayload(event.metadata, "mastery_mode"));
    if (raw?.status !== "open_session") continue;
    pointId =
      typeof raw.knowledge_point_id === "string"
        ? raw.knowledge_point_id.trim()
        : "";
  }
  return pointId;
}

/** The mode an ``open_session`` handoff switched into (``study``/``review``/``outline``). */
export function modeHandoffMode(events: StreamEvent[] | undefined): string {
  let mode = "";
  for (const event of events || []) {
    if (event.type !== "tool_result") continue;
    const raw = asRecord(toolResultPayload(event.metadata, "mastery_mode"));
    if (raw?.status !== "open_session") continue;
    mode = typeof raw.mode === "string" ? raw.mode.trim() : "";
  }
  return mode;
}

export function modeHandoffFingerprint(
  messages: readonly { role?: string; id?: number | string; events?: StreamEvent[] }[],
  sessionId: string | null,
): {
  target: string;
  knowledgePointId: string;
  mode: string;
  fingerprint: string;
} {
  let target = "";
  let knowledgePointId = "";
  let mode = "";
  let lastId: number | string = "";
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    const next = modeHandoffSession(message.events);
    if (!next) continue;
    target = next;
    knowledgePointId = modeHandoffKnowledgePoint(message.events);
    mode = modeHandoffMode(message.events);
    lastId = message.id ?? "";
  }
  return {
    target,
    knowledgePointId,
    mode,
    fingerprint: `${sessionId ?? ""}:${lastId}:${target}`,
  };
}

/** Follow a mode handoff only when it appeared after this session was opened. */
export function shouldFollowModeHandoff(input: {
  target: string;
  fingerprint: string;
  sessionId: string | null;
  baselineFingerprint: string;
}): boolean {
  if (!input.baselineFingerprint) return false;
  if (!input.target || input.target === input.sessionId) return false;
  return input.fingerprint !== input.baselineFingerprint;
}
