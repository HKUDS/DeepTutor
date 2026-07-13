import type { StreamEvent } from "@/lib/unified-ws";

type ContentMeta = {
  call_id?: string;
  call_kind?: string;
  call_state?: string;
  call_role?: string;
  trace_kind?: string;
};

function eventMeta(event: StreamEvent): ContentMeta {
  return (event.metadata ?? {}) as ContentMeta;
}

export function shouldAppendEventContent(event: StreamEvent): boolean {
  if (event.type !== "content") return false;
  const meta = eventMeta(event);
  if (!meta.call_id) return true;
  // The chat agent loop streams every round's text as `content`. The
  // tool-less finish round (and the forced-finish round) are the
  // user-facing answer; narration rounds are filtered back out via their
  // call_role marker (see collectNarrationCallIds).
  return (
    meta.call_kind === "llm_final_response" ||
    meta.call_kind === "agent_loop_round"
  );
}

/**
 * call_ids whose round resolved as "narration" — a short preamble the chat
 * loop streamed alongside a tool call. That text belongs to the trace, not
 * the answer, so it is excluded once the round's call_status marker arrives.
 */
export function collectNarrationCallIds(events: StreamEvent[]): Set<string> {
  const ids = new Set<string>();
  for (const event of events) {
    const meta = eventMeta(event);
    if (
      meta.trace_kind === "call_status" &&
      meta.call_state === "complete" &&
      meta.call_role === "narration" &&
      meta.call_id
    ) {
      ids.add(meta.call_id);
    }
  }
  return ids;
}

/** True for the per-round marker that flips a round to "narration". */
export function isNarrationMarker(event: StreamEvent): boolean {
  const meta = eventMeta(event);
  return (
    meta.trace_kind === "call_status" &&
    meta.call_state === "complete" &&
    meta.call_role === "narration"
  );
}

/**
 * Recompute the answer text from a turn's events: appended content minus any
 * narration rounds. Cheap to call only when a narration marker arrives (a
 * handful of times per turn) rather than per streamed chunk.
 */
export function recomputeAnswerContent(events: StreamEvent[]): string {
  const narration = collectNarrationCallIds(events);
  let content = "";
  for (const event of events) {
    if (!shouldAppendEventContent(event)) continue;
    const callId = eventMeta(event).call_id;
    if (callId && narration.has(callId)) continue;
    content += event.content;
  }
  return content;
}
