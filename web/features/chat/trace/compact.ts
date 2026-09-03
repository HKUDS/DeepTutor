import type { StreamEvent } from "@/features/chat/model/protocol";
import type { MessageTraceMetadata } from "@/features/chat/trace/memory";
import {
  collectNarrationCallIds,
  shouldAppendEventContent,
} from "@/lib/stream";

export const MAX_PREVIEW_EVENTS = 200;
export const MAX_PREVIEW_BYTES = 128 * 1024;
export const MAX_LEGACY_PAYLOAD_CHARS = 16 * 1024;

const TERMINAL_TYPES = new Set(["done", "error", "cancelled"]);
const utf8Encoder = new TextEncoder();
const SEMANTIC_TYPES = new Set([
  "done",
  "error",
  "cancelled",
  "result",
  "tool_call",
  "tool_result",
]);

function metadata(event: StreamEvent): Record<string, unknown> {
  return (event.metadata ?? {}) as Record<string, unknown>;
}

/** Cards must survive preview truncation; a lost card leaves stale UI. */
const CARD_METADATA_KEYS = ["ask_user", "mastery_question"] as const;

function carriesCard(event: StreamEvent): boolean {
  const meta = metadata(event);
  if (meta.ask_user_resolved) return true;
  const toolMetadata = meta.tool_metadata;
  const nested =
    typeof toolMetadata === "object" && toolMetadata !== null
      ? (toolMetadata as Record<string, unknown>)
      : null;
  return CARD_METADATA_KEYS.some(
    (key) => meta[key] || (nested && key in nested),
  );
}

function isSemantic(event: StreamEvent): boolean {
  if (SEMANTIC_TYPES.has(String(event.type ?? ""))) return true;
  return carriesCard(event);
}

function isCritical(event: StreamEvent): boolean {
  if (
    TERMINAL_TYPES.has(String(event.type ?? "")) ||
    String(event.type ?? "") === "result"
  ) {
    return true;
  }
  return carriesCard(event);
}

function boundLegacyPayload(event: StreamEvent): StreamEvent {
  let changed = false;
  const next = { ...event } as StreamEvent & { _truncated?: boolean };
  if (
    typeof event.content === "string" &&
    event.content.length > MAX_LEGACY_PAYLOAD_CHARS
  ) {
    next.content = `${event.content.slice(0, MAX_LEGACY_PAYLOAD_CHARS)}...[truncated]`;
    changed = true;
  }
  const meta = metadata(event);
  const toolMetadata = meta.tool_metadata;
  if (typeof toolMetadata === "object" && toolMetadata !== null) {
    const boundedToolMetadata = { ...(toolMetadata as Record<string, unknown>) };
    for (const field of ["content", "answer"] as const) {
      const value = boundedToolMetadata[field];
      if (
        typeof value === "string" &&
        value.length > MAX_LEGACY_PAYLOAD_CHARS
      ) {
        boundedToolMetadata[field] = `${value.slice(0, MAX_LEGACY_PAYLOAD_CHARS)}...[truncated]`;
        changed = true;
      }
    }
    if (changed) next.metadata = { ...meta, tool_metadata: boundedToolMetadata };
  }
  return (changed ? next : event) as StreamEvent;
}

export function compactTracePreview(
  events: StreamEvent[],
  maxEvents = MAX_PREVIEW_EVENTS,
  maxBytes = MAX_PREVIEW_BYTES,
): { events: StreamEvent[]; truncated: boolean } {
  const semantic = events.filter(isSemantic);
  let criticalIndices = semantic.reduce<number[]>((indices, event, index) => {
    if (isCritical(event)) indices.push(index);
    return indices;
  }, []);
  if (criticalIndices.length > maxEvents) {
    criticalIndices = criticalIndices.slice(-maxEvents);
  }
  const selectedIndices = new Set(criticalIndices);
  for (let index = semantic.length - 1; index >= 0; index -= 1) {
    if (selectedIndices.size >= maxEvents) break;
    selectedIndices.add(index);
  }
  const selected = semantic.filter((_, index) => selectedIndices.has(index));
  const result: StreamEvent[] = [];
  let usedBytes = 0;
  for (const source of selected) {
    const event = boundLegacyPayload(source);
    let size = utf8Encoder.encode(JSON.stringify(event)).length;
    if (result.length > 0 && usedBytes + size > maxBytes) continue;
    if (result.length === 0 && size > maxBytes) {
      const bounded = {
        type: event.type,
        source: "",
        stage: "",
        metadata: {},
        turn_id: event.turn_id,
        session_id: event.session_id,
        seq: event.seq,
        timestamp: event.timestamp,
        content: "...[truncated]",
        _truncated: true,
      };
      size = utf8Encoder.encode(JSON.stringify(bounded)).length;
      result.push(bounded as StreamEvent);
      usedBytes += size;
      continue;
    }
    result.push(event);
    usedBytes += size;
  }
  if (!result.some((event) => TERMINAL_TYPES.has(String(event.type ?? "")))) {
    const terminal = [...events]
      .reverse()
      .find((event) => TERMINAL_TYPES.has(String(event.type ?? "")));
    if (terminal) result.push(terminal);
  }
  return {
    events: result,
    truncated:
      events.length !== result.length || selected.length !== result.length,
  };
}

export function settleMessageTrace(
  events: StreamEvent[],
  turnId: string | null,
): { events: StreamEvent[]; trace: MessageTraceMetadata } {
  const narration = collectNarrationCallIds(events);
  let answerLength = 0;
  let lastSeq = 0;
  const stamped = events.map((event) => {
    lastSeq = Math.max(lastSeq, event.seq ?? 0);
    const meta = metadata(event);
    if (shouldAppendEventContent(event)) {
      const callId = typeof meta.call_id === "string" ? meta.call_id : "";
      if (!callId || !narration.has(callId))
        answerLength += event.content.length;
      return event;
    }
    if (
      event.type === "progress" &&
      meta.ask_user_resolved &&
      meta.assistant_content_offset === undefined
    ) {
      return {
        ...event,
        metadata: { ...meta, assistant_content_offset: answerLength },
      } as StreamEvent;
    }
    return event;
  });
  const preview = compactTracePreview(stamped);
  const stamps = events
    .map((event) => event.timestamp)
    .filter((value): value is number => typeof value === "number");
  return {
    events: preview.events,
    trace: {
      turn_id: turnId,
      total: events.length,
      last_seq: lastSeq,
      truncated: preview.truncated,
      ...(stamps.length
        ? { started_at: Math.min(...stamps), ended_at: Math.max(...stamps) }
        : {}),
    },
  };
}
