import type { StreamEvent } from "@/features/chat/model/protocol";
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

/**
 * Whether this event posed or resolved a card — a question either way.
 *
 * Both channels count: the generic `ask_user` card and the mastery course's
 * own question card. A card is the one row a settled message cannot render
 * without, so dropping one from a preview leaves the learner looking at a
 * question that is no longer there.
 */
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
    const boundedToolMetadata = {
      ...(toolMetadata as Record<string, unknown>),
    };
    for (const field of ["content", "answer"] as const) {
      const value = boundedToolMetadata[field];
      if (
        typeof value === "string" &&
        value.length > MAX_LEGACY_PAYLOAD_CHARS
      ) {
        boundedToolMetadata[field] =
          `${value.slice(0, MAX_LEGACY_PAYLOAD_CHARS)}...[truncated]`;
        changed = true;
      }
    }
    if (changed)
      next.metadata = { ...meta, tool_metadata: boundedToolMetadata };
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

/**
 * Settle a finished message on the trace it keeps in memory: the compact
 * preview, plus the handle the disclosure needs to fetch the full trace back.
 *
 * Takes the message's own events, so it has to run where those are current —
 * in the reducer. The ``done`` frame lands in the same burst as the last
 * round's content, its tool call and any card it posed; a snapshot taken
 * outside the reducer misses that burst and settles the message on a trace
 * with no card in it and a clock that stops seconds early.
 *
 * Before compaction, each card resolution is stamped with the length of the
 * answer text streamed before it — the same ``assistant_content_offset`` the
 * backend writes when it persists the event. The preview drops the content
 * events, so this offset is what still says where the card sat in the text.
 */
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
      // Measured over the full stream before it is previewed away, for the
      // same reason the server sends these: the preview drops the events that
      // mark where the turn started.
      ...(stamps.length
        ? { started_at: Math.min(...stamps), ended_at: Math.max(...stamps) }
        : {}),
    },
  };
}

export interface TraceSnapshot {
  events: StreamEvent[];
  metadata?: MessageTraceMetadata;
}

export interface MessageTraceMetadata {
  turn_id?: string | null;
  total?: number;
  last_seq?: number;
  truncated?: boolean;
  /** Wall-clock start of the whole turn, epoch seconds. Supplied because the
   *  preview keeps only tool and terminal events: the moment the turn began
   *  is never among them, so timing the preview alone starts the clock at the
   *  first tool call. */
  started_at?: number | null;
  /** Wall-clock end of the whole turn, epoch seconds. */
  ended_at?: number | null;
}

export class TraceCache {
  private readonly entries = new Map<string, TraceSnapshot>();

  constructor(private readonly capacity = 5) {}

  retain(key: string, snapshot: TraceSnapshot): Array<[string, TraceSnapshot]> {
    this.entries.delete(key);
    this.entries.set(key, snapshot);
    const evicted: Array<[string, TraceSnapshot]> = [];
    while (this.entries.size > this.capacity) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      const released = this.release(oldest);
      if (released) evicted.push([oldest, released]);
    }
    return evicted;
  }

  release(key: string): TraceSnapshot | undefined {
    const snapshot = this.entries.get(key);
    this.entries.delete(key);
    return snapshot;
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  clear(): void {
    this.entries.clear();
  }

  releaseExcept(keyPrefix: string): Array<[string, TraceSnapshot]> {
    const released: Array<[string, TraceSnapshot]> = [];
    for (const [key, snapshot] of this.entries) {
      if (key.startsWith(`${keyPrefix}:`)) continue;
      released.push([key, snapshot]);
      this.entries.delete(key);
    }
    return released;
  }

  get size(): number {
    return this.entries.size;
  }
}
