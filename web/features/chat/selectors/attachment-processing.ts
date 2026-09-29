import type { StreamEvent } from "@/features/chat/model/protocol";

export type AttachmentProcessingPhase =
  | "uploading"
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
  attachments?: Array<{ filename?: string; mime_type?: string }>;
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
  const userIndex = messages.findLastIndex((message) => message.role === "user");
  const assistantIndex = messages.findLastIndex((message) => message.role === "assistant");
  const latest = assistantIndex > userIndex ? messages[assistantIndex] : null;
  if (!latest && !isStreaming) return [];

  const byAttachment = new Map<string, AttachmentProcessingItem>();
  for (const event of latest?.events ?? []) {
    const item = parsingEvent(event);
    if (item) byAttachment.set(item.attachmentId, item);
  }
  const items = [...byAttachment.values()];
  // Before the first server progress event the PDF is travelling in the
  // start_turn WebSocket payload. This is a stage, not a byte percentage:
  // browser WebSocket.send does not expose upload progress (#1523).
  if (isStreaming && userIndex >= 0) {
    const receivedByName = new Map<string, number>();
    for (const item of items) {
      receivedByName.set(item.filename, (receivedByName.get(item.filename) ?? 0) + 1);
    }
    for (const [index, attachment] of (messages[userIndex].attachments ?? []).entries()) {
      const filename = attachment.filename ?? "";
      if (attachment.mime_type !== "application/pdf" && !filename.toLowerCase().endsWith(".pdf")) {
        continue;
      }
      const received = receivedByName.get(filename) ?? 0;
      if (received) {
        receivedByName.set(filename, received - 1);
      } else {
        items.push({
          attachmentId: `uploading:${index}`,
          filename,
          phase: "uploading",
          detail: "",
        });
      }
    }
  }
  if (isStreaming) return items;
  return items.filter(
    (item) => item.phase === "failed" || item.phase === "fallback",
  );
}
