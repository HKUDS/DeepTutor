import { wsUrl } from "@/lib/api";
import {
  ReconnectingWebSocket,
  type ReconnectingWebSocketOptions,
} from "@/lib/reconnecting-websocket";
import type { MasteryEvent } from "@/lib/learning-api";

export const MASTERY_WS_PATH = "/ws/mastery-paths";

export interface MasterySubscribedMessage {
  type: "subscribed";
  path_id: string;
  revision: number;
  events: MasteryEvent[];
}

export interface MasteryTopicEventMessage {
  type: "topic_event";
  path_id: string;
  revision: number;
  reason: string;
  sequence: number;
  events: MasteryEvent[];
}

export interface MasterySocketErrorMessage {
  type: "error";
  content: string;
}

export type MasterySocketMessage =
  | MasterySubscribedMessage
  | MasteryTopicEventMessage
  | MasterySocketErrorMessage;

export type MasterySocketEnvelope =
  | MasterySubscribedMessage
  | MasteryTopicEventMessage;

export function masterySubscribePayload(
  pathId: string,
  afterRevision: number,
): string {
  return JSON.stringify({
    type: "subscribe",
    path_id: pathId,
    after_revision: Math.max(0, Math.floor(afterRevision)),
  });
}

export function parseMasterySocketMessage(
  data: unknown,
): MasterySocketMessage | null {
  let value: unknown = data;
  if (typeof data === "string") {
    try {
      value = JSON.parse(data) as unknown;
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object") return null;
  const message = value as Record<string, unknown>;
  if (message.type === "error" && typeof message.content === "string") {
    return { type: "error", content: message.content };
  }
  if (
    (message.type !== "subscribed" && message.type !== "topic_event") ||
    typeof message.path_id !== "string" ||
    typeof message.revision !== "number" ||
    !Array.isArray(message.events)
  ) {
    return null;
  }
  if (message.type === "subscribed") {
    return message as unknown as MasterySubscribedMessage;
  }
  if (
    typeof message.reason !== "string" ||
    typeof message.sequence !== "number"
  ) {
    return null;
  }
  return message as unknown as MasteryTopicEventMessage;
}

export interface MasteryTopicSocketHandlers {
  onEnvelope: (message: MasterySocketEnvelope) => void;
  onConnecting?: () => void;
  onLive?: () => void;
  onDisconnect?: () => void;
  onError?: (message: string) => void;
}

/** One reconnecting, cursor-preserving subscription for a single topic. */
export class MasteryTopicSocket {
  private cursor: number;
  private readonly transport: ReconnectingWebSocket;

  constructor(
    private readonly pathId: string,
    private readonly handlers: MasteryTopicSocketHandlers,
    initialRevision = 0,
    options: ReconnectingWebSocketOptions = {},
  ) {
    this.cursor = Math.max(0, initialRevision);
    this.transport = new ReconnectingWebSocket(
      wsUrl(MASTERY_WS_PATH),
      {
        onOpen: () => {
          this.handlers.onConnecting?.();
          this.transport.send(
            masterySubscribePayload(this.pathId, this.cursor),
          );
        },
        onMessage: (event) => this.receive(event.data),
        onDisconnect: () => this.handlers.onDisconnect?.(),
        onError: (error) =>
          this.handlers.onError?.(String(error || "Socket error")),
      },
      options,
    );
  }

  get revision(): number {
    return this.cursor;
  }

  start(): void {
    this.handlers.onConnecting?.();
    this.transport.start();
  }

  wake(): void {
    this.transport.wake();
  }

  stop(): void {
    this.transport.stop();
  }

  private receive(data: unknown): void {
    const message = parseMasterySocketMessage(data);
    if (!message) return;
    if (message.type === "error") {
      this.handlers.onError?.(message.content);
      return;
    }
    if (message.path_id !== this.pathId) return;
    this.cursor = Math.max(this.cursor, message.revision);
    this.handlers.onLive?.();
    this.handlers.onEnvelope(message);
  }
}
