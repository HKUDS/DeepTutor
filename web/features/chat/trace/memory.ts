import type { StreamEvent } from "@/features/chat/model/protocol";

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
