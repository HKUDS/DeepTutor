import type { Emit, EngineEvent } from "./types.js";

/** Bound IPC/event retention without delaying the first token of a trace.
 * Only adjacent deltas with identical metadata merge. Status/tool events are
 * barriers. At most one bounded buffer and one sink operation are outstanding.
 */
export class EventCoalescer {
  private pending: EngineEvent | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private tail: Promise<void> = Promise.resolve();
  private failure: unknown;
  private key = "";
  private lastSent = 0;
  constructor(
    private readonly sink: Emit,
    private readonly delayMs = 16,
    private readonly maxChars = 8192,
  ) {}

  readonly emit: Emit = async (event) => {
    if (this.failure) throw this.failure;
    const mergeable = event.type === "content" || event.type === "thinking";
    const key = mergeable
      ? `${event.type}:${JSON.stringify(event.metadata)}`
      : "";
    if (!mergeable || key !== this.key) {
      await this.flush();
      this.key = key;
      await this.send(event);
      return;
    }
    // Slow streams already fit the UI cadence: forward them without waiting.
    if (!this.pending && performance.now() - this.lastSent >= this.delayMs) {
      await this.send(event);
      return;
    }
    if (
      this.pending &&
      this.pending.content.length + event.content.length > this.maxChars
    )
      await this.flush();
    if (event.content.length >= this.maxChars) {
      await this.flush();
      await this.send(event);
      return;
    }
    if (this.pending) this.pending.content += event.content;
    else this.pending = { ...event };
    if (!this.timer)
      this.timer = setTimeout(
        () => {
          void this.flush().catch(() => {});
        },
        Math.max(1, this.delayMs - (performance.now() - this.lastSent)),
      );
    // Preserve backpressure when a timer-triggered flush is awaiting the host.
    await this.tail;
    if (this.failure) throw this.failure;
  };

  private send(event: EngineEvent): Promise<void> {
    const operation = this.tail.then(async () => {
      if (this.failure) throw this.failure;
      this.lastSent = performance.now();
      await this.sink(event);
    });
    this.tail = operation.catch((error: unknown) => {
      this.failure = error;
    });
    return operation;
  }
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    const event = this.pending;
    this.pending = undefined;
    if (event) await this.send(event);
    await this.tail;
    if (this.failure) throw this.failure;
  }
  discard(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = undefined;
  }
}
