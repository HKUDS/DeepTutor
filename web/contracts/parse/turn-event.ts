import type {
  ActiveTurnInfo,
  CommandAckEvent,
  PongEvent,
  ProtocolErrorEvent,
  ServerEvent,
  StreamEvent,
  StreamEventType,
} from "@/contracts/generated/turn-protocol";

export type ParseResult<T> =
  | { ok: true; value: T }
  | {
      ok: false;
      reason: "heartbeat" | "invalid" | "unsupported";
      diagnostic: string;
    };

const STREAM_EVENT_TYPES = new Set<StreamEventType>([
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

function diagnostic(value: unknown, detail: string): string {
  if (!value || typeof value !== "object") return detail;
  const record = value as Record<string, unknown>;
  const type =
    typeof record.type === "string"
      ? record.type.slice(0, 48)
      : typeof record.type;
  const keys = Object.keys(record)
    .filter(
      (key) =>
        !["content", "metadata", "token", "password", "secret"].includes(key),
    )
    .slice(0, 12)
    .sort();
  return `${detail}; type=${type}; keys=${keys.join(",")}`;
}

function parseRaw(raw: unknown): ParseResult<unknown> {
  if (typeof raw !== "string") return { ok: true, value: raw };
  if (!raw.trim() || raw.trim() === "heartbeat") {
    return { ok: false, reason: "heartbeat", diagnostic: "heartbeat frame" };
  }
  try {
    return { ok: true, value: JSON.parse(raw) as unknown };
  } catch {
    return {
      ok: false,
      reason: "invalid",
      diagnostic: `invalid JSON frame; length=${raw.length}`,
    };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function validProtocolVersion(value: unknown): boolean {
  return value === "2.0";
}

export function parseTurnEvent(raw: unknown): ParseResult<ServerEvent> {
  const decoded = parseRaw(raw);
  if (!decoded.ok) return decoded;
  if (!isRecord(decoded.value)) {
    return {
      ok: false,
      reason: "invalid",
      diagnostic: "event is not an object",
    };
  }

  const event = decoded.value;
  if (event.type === "ping" || event.type === "heartbeat") {
    return { ok: false, reason: "heartbeat", diagnostic: "heartbeat frame" };
  }
  if (typeof event.type !== "string") {
    return {
      ok: false,
      reason: "invalid",
      diagnostic: diagnostic(event, "missing event type"),
    };
  }
  if (!validProtocolVersion(event.protocol_version)) {
    return {
      ok: false,
      reason: "unsupported",
      diagnostic: diagnostic(event, "unsupported protocol version"),
    };
  }

  if (event.type === "pong") {
    return { ok: true, value: event as unknown as PongEvent };
  }

  if (event.type === "command_ack") {
    const commandType = String(event.command_type);
    const valid =
      typeof event.command_id === "string" &&
      event.command_id.trim().length > 0 &&
      ["cancel_turn", "submit_user_reply", "user_input"].includes(
        commandType,
      ) &&
      typeof event.accepted === "boolean" &&
      (event.turn_id === undefined || typeof event.turn_id === "string") &&
      (event.error_code === undefined ||
        typeof event.error_code === "string") &&
      (event.message === undefined || typeof event.message === "string");
    if (!valid) {
      return {
        ok: false,
        reason: "invalid",
        diagnostic: diagnostic(event, "invalid command acknowledgement"),
      };
    }
    return { ok: true, value: event as unknown as CommandAckEvent };
  }

  if (event.type === "protocol_error") {
    const valid =
      typeof event.error_code === "string" &&
      event.error_code.trim().length > 0 &&
      typeof event.message === "string" &&
      typeof event.retryable === "boolean";
    if (!valid) {
      return {
        ok: false,
        reason: "invalid",
        diagnostic: diagnostic(event, "invalid protocol error"),
      };
    }
    return { ok: true, value: event as unknown as ProtocolErrorEvent };
  }

  if (event.type === "active_turn_info") {
    const validStatus = new Set([
      "none",
      "queued",
      "running",
      "waiting_input",
      "recovering",
      "completed",
      "failed",
      "cancelled",
    ]).has(String(event.status));
    if (
      !validStatus ||
      (event.turn_id !== undefined && typeof event.turn_id !== "string")
    ) {
      return {
        ok: false,
        reason: "invalid",
        diagnostic: diagnostic(event, "invalid active-turn envelope"),
      };
    }
    return { ok: true, value: event as unknown as ActiveTurnInfo };
  }

  if (!STREAM_EVENT_TYPES.has(event.type as StreamEventType)) {
    return {
      ok: false,
      reason: "unsupported",
      diagnostic: diagnostic(event, "unknown event type"),
    };
  }

  const valid =
    typeof event.turn_id === "string" &&
    event.turn_id.trim().length > 0 &&
    Number.isInteger(event.seq) &&
    Number(event.seq) >= 0 &&
    typeof event.timestamp === "number" &&
    Number.isFinite(event.timestamp) &&
    (event.content === undefined || typeof event.content === "string") &&
    (event.source === undefined || typeof event.source === "string") &&
    (event.stage === undefined || typeof event.stage === "string") &&
    (event.session_id === undefined || typeof event.session_id === "string") &&
    (event.metadata === undefined || isRecord(event.metadata));

  if (!valid) {
    return {
      ok: false,
      reason: "invalid",
      diagnostic: diagnostic(event, "invalid stream envelope"),
    };
  }

  return {
    ok: true,
    value: {
      ...event,
      content: event.content ?? "",
      metadata: event.metadata ?? {},
      protocol_version: "2.0",
      seq: event.seq,
      session_id: event.session_id ?? "",
      source: event.source ?? "",
      stage: event.stage ?? "",
    } as StreamEvent,
  };
}
