import type { StreamEvent } from "@/features/chat/model/protocol";

type ContentMeta = {
  call_id?: string;
  call_kind?: string;
  call_state?: string;
  call_role?: string;
  answer_visible?: boolean;
  trace_kind?: string;
};

function eventMeta(event: StreamEvent): ContentMeta {
  return (event.metadata ?? {}) as ContentMeta;
}

export function shouldAppendEventContent(event: StreamEvent): boolean {
  if (event.type !== "content") return false;
  const meta = eventMeta(event);
  if (!meta.call_id) return true;
  // The chat agent loop streams every round's text as `content`, and all of
  // it is the answer — the commentary a round wrote before calling a tool
  // included. Only a round the backend retracts is filtered back out (see
  // collectRetractedCallIds).
  return (
    meta.call_kind === "llm_final_response" ||
    meta.call_kind === "agent_loop_round"
  );
}

/**
 * call_ids whose round was taken back out of the answer.
 *
 * A round that called tools still wrote answer text: the reader watched that
 * sentence arrive above the tool's own row, so it stays where they saw it.
 * The one exception is a round a capability's finish guard rejected — the
 * backend republishes that round's marker with `answer_visible: false`, and
 * the text moves into the trace.
 */
export function collectRetractedCallIds(events: StreamEvent[]): Set<string> {
  const ids = new Set<string>();
  for (const event of events) {
    const meta = eventMeta(event);
    if (
      meta.trace_kind === "call_status" &&
      meta.call_state === "complete" &&
      meta.answer_visible === false &&
      meta.call_id
    ) {
      ids.add(meta.call_id);
    }
  }
  return ids;
}

/** True for a per-round marker that takes its content back out of the answer. */
export function isRetractionMarker(event: StreamEvent): boolean {
  const meta = eventMeta(event);
  return (
    meta.trace_kind === "call_status" &&
    meta.call_state === "complete" &&
    meta.answer_visible === false
  );
}

/**
 * Recompute the answer text from a turn's events: appended content minus any
 * retracted round. Cheap to call only when a retraction arrives (rare — most
 * turns never have one) rather than per streamed chunk.
 */
export function recomputeAnswerContent(events: StreamEvent[]): string {
  const retracted = collectRetractedCallIds(events);
  let content = "";
  for (const event of events) {
    if (!shouldAppendEventContent(event)) continue;
    const callId = eventMeta(event).call_id;
    if (callId && retracted.has(callId)) continue;
    content += event.content;
  }
  return content;
}
