import type {
  CancelTurnCommand,
  CheckActiveTurnCommand,
  PingCommand,
  RegenerateCommand,
  ResumeTurnCommand,
  StartTurnCommand,
  SubmitUserReplyCommand,
  SubscribeSessionCommand,
  SubscribeTurnCommand,
  UnsubscribeCommand,
  UserAnswer,
  UserInputCommand,
} from "@/contracts/generated/turn-protocol";

const PROTOCOL_VERSION = "2.0" as const;

function id(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new TypeError(`${field} must not be empty`);
  return normalized;
}

function sequence(value: number): number {
  if (!Number.isInteger(value) || value < 0) {
    throw new TypeError("after_seq must be a non-negative integer");
  }
  return value;
}

function commandId(value?: string): string {
  if (value !== undefined) return id(value, "command_id");
  return globalThis.crypto.randomUUID();
}

export function buildStartTurn(
  input: Omit<StartTurnCommand, "type" | "protocol_version">,
): StartTurnCommand {
  return { ...input, type: "start_turn", protocol_version: PROTOCOL_VERSION };
}

export function buildSubscribeTurn(input: {
  turnId: string;
  afterSeq?: number;
}): SubscribeTurnCommand {
  return {
    type: "subscribe_turn",
    turn_id: id(input.turnId, "turn_id"),
    after_seq: sequence(input.afterSeq ?? 0),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildSubscribeSession(input: {
  sessionId: string;
  afterSeq?: number;
}): SubscribeSessionCommand {
  return {
    type: "subscribe_session",
    session_id: id(input.sessionId, "session_id"),
    after_seq: sequence(input.afterSeq ?? 0),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildResumeTurn(input: {
  turnId: string;
  afterSeq?: number;
}): ResumeTurnCommand & {
  type: "resume_from";
  turn_id: string;
  seq: number;
  protocol_version: "2.0";
} {
  return {
    type: "resume_from",
    turn_id: id(input.turnId, "turn_id"),
    seq: sequence(input.afterSeq ?? 0),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildCancelTurn(
  turnId: string,
  stableCommandId?: string,
): CancelTurnCommand {
  return {
    type: "cancel_turn",
    turn_id: id(turnId, "turn_id"),
    command_id: commandId(stableCommandId),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildRegenerate(input: {
  sessionId: string;
  overrides?: Record<string, unknown>;
}): RegenerateCommand {
  return {
    type: "regenerate",
    session_id: id(input.sessionId, "session_id"),
    overrides: input.overrides ?? {},
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildSubmitUserReply(input: {
  turnId: string;
  text?: string;
  answers?: UserAnswer[];
  commandId?: string;
}): SubmitUserReplyCommand {
  if (input.text === undefined && !input.answers?.length) {
    throw new TypeError("submit_user_reply requires text or answers");
  }
  return {
    type: "submit_user_reply",
    turn_id: id(input.turnId, "turn_id"),
    text: input.text,
    answers: input.answers,
    command_id: commandId(input.commandId),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildUserInput(input: {
  turnId: string;
  content: string;
  commandId?: string;
}): UserInputCommand {
  return {
    type: "user_input",
    turn_id: id(input.turnId, "turn_id"),
    content: input.content,
    command_id: commandId(input.commandId),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildCheckActiveTurn(
  sessionId: string,
): CheckActiveTurnCommand {
  return {
    type: "check_active_turn",
    session_id: id(sessionId, "session_id"),
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildUnsubscribe(input: {
  turnId?: string;
  sessionId?: string;
}): UnsubscribeCommand {
  if (!input.turnId && !input.sessionId)
    throw new TypeError("unsubscribe requires a target");
  return {
    type: "unsubscribe",
    turn_id: input.turnId ? id(input.turnId, "turn_id") : undefined,
    session_id: input.sessionId ? id(input.sessionId, "session_id") : undefined,
    protocol_version: PROTOCOL_VERSION,
  };
}

export function buildPing(): PingCommand {
  return { type: "ping", protocol_version: PROTOCOL_VERSION };
}
