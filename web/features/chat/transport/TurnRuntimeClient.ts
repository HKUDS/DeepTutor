import type {
  ClientCommand,
  ServerEvent,
  StreamEvent,
} from "@/contracts/generated/turn-protocol";
import { buildPing, buildResumeTurn } from "@/contracts/parse/turn-command";
import { parseTurnEvent } from "@/contracts/parse/turn-event";

import {
  browserSocketFactory,
  SOCKET_CONNECTING,
  SOCKET_OPEN,
  type TurnSocket,
  type TurnSocketFactory,
} from "./socket";
import { reconnectDelay, shouldReconnect } from "./reconnect-policy";

export type RuntimeConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "recovering"
  | "stopped";

export interface RuntimeScheduler {
  setTimeout(callback: () => void, delay: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface TurnRuntimeClientOptions {
  url?: string;
  socketFactory?: TurnSocketFactory;
  scheduler?: RuntimeScheduler;
  random?: () => number;
  maxBufferedGap?: number;
  replayProbeDelayMs?: number;
  onEvent: (event: ServerEvent) => void;
  onStateChange?: (state: RuntimeConnectionState) => void;
  onDiagnostic?: (diagnostic: string) => void;
  onReconcile?: (cursor: { turnId: string; afterSeq: number }) => void;
}

interface PendingCommand {
  command: ClientCommand;
  commandId: string | null;
  requiresAck: boolean;
  acknowledgedAfter: number;
  sentGeneration: number;
  /** Settled with the server's verdict, for callers that await one. */
  settle?: (accepted: boolean) => void;
}

const ACKNOWLEDGED_COMMAND_TYPES = new Set([
  "cancel_turn",
  "submit_user_reply",
  "user_input",
]);

function prepareCommand(command: ClientCommand): {
  command: ClientCommand;
  commandId: string | null;
  requiresAck: boolean;
} {
  const requiresAck =
    typeof command.type === "string" &&
    ACKNOWLEDGED_COMMAND_TYPES.has(command.type);
  if (!requiresAck) return { command, commandId: null, requiresAck: false };
  const record = command as unknown as Record<string, unknown>;
  const existing =
    typeof record.command_id === "string" ? record.command_id.trim() : "";
  const commandId = existing || globalThis.crypto.randomUUID();
  return {
    command: { ...command, command_id: commandId } as ClientCommand,
    commandId,
    requiresAck: true,
  };
}

const defaultScheduler: RuntimeScheduler = {
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: (handle) =>
    globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class TurnRuntimeClient {
  private readonly options: Required<
    Pick<
      TurnRuntimeClientOptions,
      | "url"
      | "socketFactory"
      | "scheduler"
      | "random"
      | "maxBufferedGap"
      | "replayProbeDelayMs"
    >
  > &
    Omit<
      TurnRuntimeClientOptions,
      | "url"
      | "socketFactory"
      | "scheduler"
      | "random"
      | "maxBufferedGap"
      | "replayProbeDelayMs"
    >;
  private socket: TurnSocket | null = null;
  private reconnectHandle: unknown = null;
  private replayProbeHandle: unknown = null;
  private reconnectAttempt = 0;
  private generation = 0;
  private stopped = false;
  private pageVisible = true;
  private turnId: string | null = null;
  private lastSeq = 0;
  private buffered = new Map<number, StreamEvent>();
  private pending: PendingCommand[] = [];
  private connectionState: RuntimeConnectionState = "idle";
  private terminalObserved = false;

  constructor(options: TurnRuntimeClientOptions) {
    this.options = {
      url: "/ws",
      socketFactory: browserSocketFactory,
      scheduler: defaultScheduler,
      random: Math.random,
      maxBufferedGap: 32,
      replayProbeDelayMs: 5_000,
      ...options,
    };
  }

  get state(): RuntimeConnectionState {
    return this.connectionState;
  }

  get cursor(): { turnId: string | null; afterSeq: number } {
    return { turnId: this.turnId, afterSeq: this.lastSeq };
  }

  connect(): void {
    if (this.stopped) this.stopped = false;
    if (this.socket && this.socket.readyState <= SOCKET_OPEN) return;
    this.clearReconnect();
    this.setState(this.turnId ? "recovering" : "connecting");
    const socket = this.options.socketFactory(this.options.url);
    this.socket = socket;

    socket.addEventListener("open", () => this.handleOpen(socket));
    socket.addEventListener("message", (event) =>
      this.handleMessage(socket, event.data),
    );
    socket.addEventListener("close", () => this.handleClose(socket));
    socket.addEventListener("error", () => {
      if (socket === this.socket)
        this.options.onDiagnostic?.("turn socket error; awaiting close");
    });
  }

  setResumeCursor(turnId: string | null, afterSeq: number): void {
    if (!Number.isInteger(afterSeq) || afterSeq < 0)
      throw new TypeError("afterSeq is invalid");
    const nextTurnId = turnId?.trim() || null;
    if (nextTurnId !== this.turnId) {
      this.clearReplayProbe();
      this.turnId = nextTurnId;
      this.lastSeq = afterSeq;
      this.buffered.clear();
      this.terminalObserved = false;
      return;
    }
    // React state can trail the socket by one render. Never rewind a live
    // transport cursor from that stale snapshot or already-consumed events
    // (including DONE) can be replayed into a new UI state.
    if (afterSeq <= this.lastSeq) return;
    this.lastSeq = afterSeq;
    for (const seq of this.buffered.keys()) {
      if (seq <= afterSeq) this.buffered.delete(seq);
    }
  }

  setPageVisible(visible: boolean): void {
    this.pageVisible = visible;
    if (visible && !this.stopped && !this.socket) this.manualRetry();
  }

  send(command: ClientCommand, options: { durable?: boolean } = {}): void {
    const durable = options.durable ?? command.type !== "ping";
    if (!durable) {
      this.sendNow(command);
      return;
    }
    this.enqueue(command);
  }

  /**
   * Send a command and resolve with the server's verdict on it.
   *
   * A command the server declines — a reply for a turn that is no longer
   * waiting, most often because the backend restarted since the question was
   * asked — is otherwise only a console diagnostic, which leaves whatever UI
   * is waiting on it pending forever. Resolves ``false`` for a rejection and
   * for a client that stops before the acknowledgement arrives; a command
   * type the protocol never acknowledges resolves ``true`` on dispatch.
   */
  sendAwaitingAck(command: ClientCommand): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      const pending = this.enqueue(command);
      if (!pending.requiresAck) {
        resolve(true);
        return;
      }
      pending.settle = resolve;
    });
  }

  private enqueue(command: ClientCommand): PendingCommand {
    const prepared = prepareCommand(command);
    const pending: PendingCommand = {
      ...prepared,
      acknowledgedAfter: this.lastSeq,
      sentGeneration: -1,
    };
    this.pending.push(pending);
    this.flushPending();
    return pending;
  }

  cancel(command: ClientCommand): void {
    this.send(command);
  }

  ping(): void {
    this.send(buildPing(), { durable: false });
  }

  manualRetry(): void {
    if (this.stopped) return;
    this.reconnectAttempt = 0;
    if (this.socket?.readyState === SOCKET_CONNECTING) return;
    this.socket?.close();
    this.socket = null;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearReconnect();
    this.clearReplayProbe();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "client stopped");
    // Nobody is left to acknowledge these, so release their waiters rather
    // than leaving the UI that sent them pending forever.
    for (const pending of this.pending) pending.settle?.(false);
    this.pending = [];
    this.buffered.clear();
    this.setState("stopped");
  }

  private handleOpen(socket: TurnSocket): void {
    if (socket !== this.socket || this.stopped) return;
    this.generation += 1;
    this.reconnectAttempt = 0;
    this.setState("connected");
    if (this.turnId) {
      this.sendNow(
        buildResumeTurn({ turnId: this.turnId, afterSeq: this.lastSeq }),
      );
    }
    this.flushPending();
  }

  private handleMessage(socket: TurnSocket, raw: unknown): void {
    if (socket !== this.socket || this.stopped) return;
    const parsed = parseTurnEvent(raw);
    if (!parsed.ok) {
      if (parsed.reason !== "heartbeat")
        this.options.onDiagnostic?.(parsed.diagnostic);
      return;
    }
    const event = parsed.value;
    if (event.type === "command_ack") {
      const remaining: PendingCommand[] = [];
      for (const item of this.pending) {
        if (item.commandId === event.command_id) item.settle?.(event.accepted);
        else remaining.push(item);
      }
      this.pending = remaining;
      if (!event.accepted) {
        this.options.onDiagnostic?.(
          `turn command rejected; type=${event.command_type}; code=${event.error_code || "rejected"}`,
        );
      }
      this.options.onEvent(event);
      return;
    }
    if (event.type === "protocol_error") {
      this.options.onDiagnostic?.(
        `turn protocol error; code=${event.error_code}; retryable=${String(event.retryable)}`,
      );
      this.options.onEvent(event);
      return;
    }
    if (event.type === "active_turn_info") {
      if (event.turn_id) this.turnId = event.turn_id;
      this.options.onEvent(event);
      return;
    }
    if (event.type === "pong") return;
    this.acceptStreamEvent(event as StreamEvent);
  }

  private acceptStreamEvent(event: StreamEvent): void {
    const eventTurnId = event.turn_id?.trim() || null;
    if (eventTurnId && eventTurnId !== this.turnId) {
      this.clearReplayProbe();
      this.turnId = eventTurnId;
      this.lastSeq = 0;
      this.buffered.clear();
      this.terminalObserved = false;
    }
    const seq = event.seq ?? 0;
    if (seq <= this.lastSeq) return;
    const gap = seq - this.lastSeq;
    if (gap > 1) {
      if (gap <= this.options.maxBufferedGap) {
        this.buffered.set(seq, event);
        // WebSockets preserve frame order, so a bounded gap is normally a
        // dropped/rejected frame rather than harmless reordering. Give an
        // in-flight predecessor one tick to arrive, then replay the durable
        // suffix instead of buffering DONE forever.
        this.scheduleReplayProbe(
          Math.min(250, this.options.replayProbeDelayMs),
        );
      } else if (this.turnId) {
        this.options.onDiagnostic?.(
          `turn event gap exceeded buffer; after_seq=${this.lastSeq}`,
        );
        this.requestReplay();
      }
      return;
    }

    this.emitInOrder(event);
    let next = this.buffered.get(this.lastSeq + 1);
    while (next) {
      this.buffered.delete(this.lastSeq + 1);
      this.emitInOrder(next);
      next = this.buffered.get(this.lastSeq + 1);
    }
  }

  private emitInOrder(event: StreamEvent): void {
    this.lastSeq = event.seq ?? this.lastSeq;
    this.pending = this.pending.filter(
      (item) => item.requiresAck || this.lastSeq <= item.acknowledgedAfter,
    );
    if (event.type === "done") {
      this.terminalObserved = true;
      this.clearReplayProbe();
    }
    this.options.onEvent(event);
    if (event.type === "done") return;
    if (!this.terminalObserved) this.scheduleReplayProbe();
  }

  private handleClose(socket: TurnSocket): void {
    if (socket !== this.socket) return;
    this.socket = null;
    this.clearReplayProbe();
    if (this.stopped) return;
    this.setState(this.turnId ? "recovering" : "connecting");
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (
      !shouldReconnect({
        attempt: this.reconnectAttempt,
        activeTurnId: this.turnId,
        pageVisible: this.pageVisible,
      })
    ) {
      this.setState("idle");
      return;
    }
    const delay = reconnectDelay(this.reconnectAttempt, this.options.random);
    this.reconnectAttempt += 1;
    this.reconnectHandle = this.options.scheduler.setTimeout(() => {
      this.reconnectHandle = null;
      this.connect();
    }, delay);
  }

  private flushPending(): void {
    if (!this.socket || this.socket.readyState !== SOCKET_OPEN) return;
    for (const pending of this.pending) {
      if (pending.sentGeneration === this.generation) continue;
      this.sendNow(pending.command);
      pending.sentGeneration = this.generation;
    }
  }

  private sendNow(command: ClientCommand): void {
    if (!this.socket || this.socket.readyState !== SOCKET_OPEN) return;
    this.socket.send(JSON.stringify(command));
  }

  private clearReconnect(): void {
    if (this.reconnectHandle === null) return;
    this.options.scheduler.clearTimeout(this.reconnectHandle);
    this.reconnectHandle = null;
  }

  private scheduleReplayProbe(delay = this.options.replayProbeDelayMs): void {
    if (!this.turnId || this.terminalObserved || this.stopped) return;
    this.clearReplayProbe();
    this.replayProbeHandle = this.options.scheduler.setTimeout(() => {
      this.replayProbeHandle = null;
      this.requestReplay();
    }, delay);
  }

  private requestReplay(): void {
    if (!this.turnId || this.terminalObserved || this.stopped) return;
    const cursor = { turnId: this.turnId, afterSeq: this.lastSeq };
    this.options.onReconcile?.(cursor);
    this.sendNow(buildResumeTurn(cursor));
  }

  private clearReplayProbe(): void {
    if (this.replayProbeHandle === null) return;
    this.options.scheduler.clearTimeout(this.replayProbeHandle);
    this.replayProbeHandle = null;
  }

  private setState(state: RuntimeConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.options.onStateChange?.(state);
  }
}
