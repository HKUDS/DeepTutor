import type {
  ClientCommand,
  ServerEvent,
} from "@/contracts/generated/turn-protocol";

import type {
  ChatMessage,
  StreamEvent,
  StreamEventType,
} from "../model/protocol";
import {
  TurnRuntimeClient,
  type RuntimeConnectionState,
} from "./TurnRuntimeClient";

const STREAM_TYPES = new Set<StreamEventType>([
  "stage_start",
  "stage_end",
  "thinking",
  "observation",
  "content",
  "tool_call",
  "tool_result",
  "progress",
  "sources",
  "result",
  "error",
  "session",
  "session_meta",
  "wait_for_input",
  "done",
]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function toStreamEvent(event: ServerEvent): StreamEvent | null {
  const raw = event as unknown as Record<string, unknown>;
  const type = raw.type;
  if (typeof type !== "string" || !STREAM_TYPES.has(type as StreamEventType))
    return null;
  return {
    type: type as StreamEventType,
    source: typeof raw.source === "string" ? raw.source : "",
    stage: typeof raw.stage === "string" ? raw.stage : "",
    content: typeof raw.content === "string" ? raw.content : "",
    metadata: asRecord(raw.metadata),
    session_id: typeof raw.session_id === "string" ? raw.session_id : undefined,
    turn_id: typeof raw.turn_id === "string" ? raw.turn_id : undefined,
    seq: typeof raw.seq === "number" ? raw.seq : undefined,
    timestamp:
      typeof raw.timestamp === "number" ? raw.timestamp : Date.now() / 1000,
  };
}

type OutboundTurnCommand = ChatMessage | ClientCommand;

function command(message: OutboundTurnCommand): ClientCommand {
  if ("protocol_version" in message && message.protocol_version === "2.0") {
    return message as ClientCommand;
  }
  return { ...message, protocol_version: "2.0" } as ClientCommand;
}

/** Transitional surface API backed entirely by the validated v2 runtime. */
export class UnifiedTurnClient {
  private readonly runtime: TurnRuntimeClient;
  private connectionState: RuntimeConnectionState = "idle";
  private closeNotified = false;

  constructor(onEvent: (event: StreamEvent) => void, onClose?: () => void) {
    this.runtime = new TurnRuntimeClient({
      onEvent(event) {
        const streamEvent = toStreamEvent(event);
        if (streamEvent) onEvent(streamEvent);
      },
      onStateChange: (state) => {
        this.connectionState = state;
        if (state === "idle" && !this.closeNotified) {
          this.closeNotified = true;
          onClose?.();
        }
        if (state === "connected") this.closeNotified = false;
      },
    });
  }

  get connected(): boolean {
    return this.connectionState === "connected";
  }

  setResumeState(turnId: string | null, seq: number): void {
    this.runtime.setResumeCursor(turnId, seq);
  }

  connect(): void {
    this.runtime.connect();
  }

  send(message: OutboundTurnCommand): void {
    this.runtime.send(command(message));
  }

  /** Send, and resolve with whether the server accepted the command. */
  sendAwaitingAck(message: OutboundTurnCommand): Promise<boolean> {
    return this.runtime.sendAwaitingAck(command(message));
  }

  disconnect(): void {
    this.runtime.stop();
    this.runtime.setResumeCursor(null, 0);
    this.connectionState = "stopped";
  }
}
