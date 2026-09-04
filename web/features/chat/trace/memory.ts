import type { StreamEvent } from "@/features/chat/model/protocol";

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

function isSemantic(event: StreamEvent): boolean {
  if (SEMANTIC_TYPES.has(String(event.type ?? ""))) return true;
  const meta = metadata(event);
  const toolMetadata = meta.tool_metadata;
  return Boolean(
    meta.ask_user ||
      meta.ask_user_resolved ||
      (typeof toolMetadata === "object" &&
        toolMetadata !== null &&
        "ask_user" in toolMetadata),
  );
}

function isCritical(event: StreamEvent): boolean {
  if (TERMINAL_TYPES.has(String(event.type ?? "")) || String(event.type ?? "") === "result") {
    return true;
  }
  const meta = metadata(event);
  const toolMetadata = meta.tool_metadata;
  return Boolean(
    meta.ask_user ||
      meta.ask_user_resolved ||
      (typeof toolMetadata === "object" &&
        toolMetadata !== null &&
        "ask_user" in toolMetadata),
  );
}

function boundLegacyPayload(event: StreamEvent): StreamEvent {
  let changed = false;
  const next = { ...event } as StreamEvent & { _truncated?: boolean };
  if (typeof event.content === "string" && event.content.length > MAX_LEGACY_PAYLOAD_CHARS) {
    next.content = `${event.content.slice(0, MAX_LEGACY_PAYLOAD_CHARS)}...[truncated]`;
    changed = true;
  }
  const meta = metadata(event);
  const toolMetadata = meta.tool_metadata;
  if (typeof toolMetadata === "object" && toolMetadata !== null) {
    const boundedToolMetadata = { ...(toolMetadata as Record<string, unknown>) };
    for (const field of ["content", "answer"] as const) {
      const value = boundedToolMetadata[field];
      if (typeof value === "string" && value.length > MAX_LEGACY_PAYLOAD_CHARS) {
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
    const terminal = [...events].reverse().find((event) => TERMINAL_TYPES.has(String(event.type ?? "")));
    if (terminal) result.push(terminal);
  }
  return {
    events: result,
    truncated: events.length !== result.length || selected.length !== result.length,
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
