import type { StreamEvent } from "@/features/chat/model/protocol";

export type AttachmentProcessingPhase =
  | "received"
  | "submitting"
  | "parsing"
  | "retrieving"
  | "completed"
  | "fallback"
  | "failed";

export interface AttachmentProcessingItem {
  attachmentId: string;
  filename: string;
  phase: AttachmentProcessingPhase;
  detail: string;
}

interface MessageWithEvents {
  role: string;
  events?: StreamEvent[];
}

const PHASES = new Set<AttachmentProcessingPhase>([
  "received",
  "submitting",
  "parsing",
  "retrieving",
  "completed",
  "fallback",
  "failed",
]);

function parsingEvent(event: StreamEvent): AttachmentProcessingItem | null {
  if (event.type !== "progress" || event.source !== "attachment_parsing") {
    return null;
  }
  const phase = String(event.metadata.phase || event.stage || "");
  if (!PHASES.has(phase as AttachmentProcessingPhase)) return null;
  const attachmentId = String(event.metadata.attachment_id || "");
  const filename = String(event.metadata.filename || "PDF attachment");
  return {
    attachmentId: attachmentId || filename,
    filename,
    phase: phase as AttachmentProcessingPhase,
    detail: event.content.trim(),
  };
}

/**
 * Return the latest truthful parser state for every PDF in the latest turn.
 * Successful terminal rows disappear when the turn settles; warnings and
 * failures remain visible so the learner can inspect them after the answer.
 */
export function selectAttachmentProcessing(
  messages: MessageWithEvents[],
  isStreaming: boolean,
): AttachmentProcessingItem[] {
  const latest = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  if (!latest) return [];

  const byAttachment = new Map<string, AttachmentProcessingItem>();
  for (const event of latest.events ?? []) {
    const item = parsingEvent(event);
    if (item) byAttachment.set(item.attachmentId, item);
  }
  const items = [...byAttachment.values()];
  if (isStreaming) return items;
  return items.filter(
    (item) => item.phase === "failed" || item.phase === "fallback",
  );
}
