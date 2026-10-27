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

export function modeHandoffFingerprint(
  messages: readonly { role?: string; id?: number | string; events?: StreamEvent[] }[],
  sessionId: string | null,
): { target: string; fingerprint: string } {
  let target = "";
  let lastId: number | string = "";
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    const next = modeHandoffSession(message.events);
    if (!next) continue;
    target = next;
    lastId = message.id ?? "";
  }
  return { target, fingerprint: `${sessionId ?? ""}:${lastId}:${target}` };
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
