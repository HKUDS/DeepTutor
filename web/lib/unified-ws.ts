/**
 * Unified WebSocket Client
 *
 * Connects to the single `/api/v1/ws` endpoint and provides
 * a typed streaming interface for the new ChatOrchestrator protocol.
 *
 * Features:
 * - Client-side heartbeat (30s ping / 45s dead-connection detection)
 * - Auto-reconnect with exponential backoff (max 5 attempts)
 * - resume_from after reconnection to continue a streaming turn
 */

import { wsUrl } from "./api";

// ---- StreamEvent types (mirror Python StreamEventType) ----

export type StreamEventType =
  | "stage_start"
  | "stage_end"
  | "thinking"
  | "observation"
  | "content"
  | "tool_call"
  | "tool_result"
  | "progress"
  | "sources"
  | "result"
  | "error"
  | "session"
  | "session_meta"
  | "done";

export interface StreamEvent {
  type: StreamEventType;
  source: string;
  stage: string;
  content: string;
  metadata: Record<string, unknown>;
  session_id?: string;
  turn_id?: string;
  seq?: number;
  timestamp: number;
}

export interface LLMSelection {
  profile_id: string;
  model_id: string;
}

// ---- Client message ----

export interface StartTurnMessage {
  type: "message" | "start_turn";
  content: string;
  tools?: string[];
  capability?: string | null;
  knowledge_bases?: string[];
  session_id?: string | null;
  attachments?: {
    type: string;
    url?: string;
    base64?: string;
    filename?: string;
    mime_type?: string;
  }[];
  language?: string;
  config?: Record<string, unknown>;
  notebook_references?: {
    notebook_id: string;
    record_ids: string[];
  }[];
  history_references?: string[];
  question_notebook_references?: number[];
  book_references?: {
    book_id: string;
    page_ids: string[];
  }[];
  persona?: string;
  llm_selection?: LLMSelection | null;
  /** Edit-branching: when present (even as ``null``) the new user message
   *  attaches at this exact parent — creating a sibling rather than
   *  appending to the session tail. */
  parent_message_id?: number | null;
}

export interface SubscribeTurnMessage {
  type: "subscribe_turn";
  turn_id: string;
  after_seq?: number;
}

export interface SubscribeSessionMessage {
  type: "subscribe_session";
  session_id: string;
  after_seq?: number;
}

export interface ResumeTurnMessage {
  type: "resume_from";
  turn_id: string;
  seq?: number;
}

export interface UnsubscribeMessage {
  type: "unsubscribe";
  turn_id?: string;
  session_id?: string;
}

export interface CancelTurnMessage {
  type: "cancel_turn";
  turn_id: string;
}

export interface RegenerateMessage {
  type: "regenerate";
  session_id: string;
  overrides?: Record<string, unknown>;
}

/**
 * Deliver the user's answer for an ``ask_user`` paused turn so the
 * agentic loop can resume on the same turn. The user's reply is
 * substituted into the matching ``role=tool`` message body before the
 * next LLM iteration runs.
 *
 * Either ``text`` (legacy single-question shape) or ``answers``
 * (v2 multi-question shape) must be provided. When both are present
 * the backend prefers ``answers``.
 */
export interface SubmitUserReplyMessage {
  type: "submit_user_reply";
  turn_id: string;
  text?: string;
  answers?: Array<{ questionId: string; text: string }>;
}

export type ChatMessage =
  | StartTurnMessage
  | SubscribeTurnMessage
  | SubscribeSessionMessage
  | ResumeTurnMessage
  | UnsubscribeMessage
  | CancelTurnMessage
  | RegenerateMessage
  | SubmitUserReplyMessage;

// ---- Connection manager ----

export type EventHandler = (event: StreamEvent) => void;

const HEARTBEAT_INTERVAL_MS = 30_000;
const HEARTBEAT_TIMEOUT_MS = 45_000;
const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 200;

export class UnifiedWSClient {
  private ws: WebSocket | null = null;
  private onEvent: EventHandler;
  private onClose?: () => void;

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private lastReceivedAt = 0;

  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private activeTurnId: string | null = null;
  private lastSeq = 0;

  constructor(onEvent: EventHandler, onClose?: () => void) {
    this.onEvent = onEvent;
    this.onClose = onClose;
  }

  /** Provide the current turn/seq so reconnection can resume the stream. */
  setResumeState(turnId: string | null, seq: number): void {
    this.activeTurnId = turnId;
    this.lastSeq = seq;
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    this.intentionalClose = false;

    const url = wsUrl("/api/v1/ws");
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.lastReceivedAt = Date.now();
      this.startHeartbeat();

      if (this.activeTurnId) {
        this.send({
          type: "resume_from",
          turn_id: this.activeTurnId,
          seq: this.lastSeq,
        });
      }
    };

    this.ws.onmessage = (ev) => {
      this.lastReceivedAt = Date.now();
      try {
        const event: StreamEvent = JSON.parse(ev.data);
        // Heartbeat frames (client-sent ``ping`` echoed by some legacy
        // backends, or ``pong`` from the modern handler) keep the socket
        // alive but are not user-visible chat events. They MUST be dropped
        // here — otherwise the message list renders them as "Unknown type"
        // error rows, especially during long-running turns.
        const type = (event as { type?: string }).type;
        if (type === "ping" || type === "pong") return;
        if (event.turn_id) this.activeTurnId = event.turn_id;
        if (event.seq != null) this.lastSeq = Math.max(this.lastSeq, event.seq);
        this.onEvent(event);
      } catch {
        console.warn("Unparseable WS message:", ev.data);
      }
    };

    this.ws.onclose = () => {
      this.ws = null;
      this.stopHeartbeat();
      if (!this.intentionalClose) {
        this.attemptReconnect();
      }
    };

    this.ws.onerror = (err) => {
      console.error("WS error:", err);
    };
  }

  send(msg: ChatMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error("WebSocket not connected");
      return;
    }
    this.ws.send(JSON.stringify(msg));
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    this.clearReconnectTimer();
    this.ws?.close();
    this.ws = null;
    this.resetResumeState();
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  // ---- Heartbeat ----

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

      if (Date.now() - this.lastReceivedAt > HEARTBEAT_TIMEOUT_MS) {
        this.ws.close();
        return;
      }

      try {
        this.ws.send(JSON.stringify({ type: "ping" }));
      } catch {
        // send may fail if socket is closing
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // ---- Reconnect ----

  private attemptReconnect(): void {
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      this.resetResumeState();
      this.onClose?.();
      return;
    }

    const delay = BASE_RECONNECT_DELAY_MS * Math.pow(2, this.reconnectAttempt);
    this.reconnectAttempt += 1;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private resetResumeState(): void {
    this.activeTurnId = null;
    this.lastSeq = 0;
    this.reconnectAttempt = 0;
  }
}
