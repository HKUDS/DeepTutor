import type {
  TurnQueryState,
  TurnStatus,
} from "@/contracts/generated/turn-protocol";
import type { AppError } from "@/shared/api/errors";

import { normalizeTurnFailure, type TurnFailure } from "./errors";

export type TurnTransportState =
  | "connected"
  | "connecting"
  | "recovering"
  | "offline";

export type TurnViewState =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "queued" }
  | { kind: "running" }
  | { kind: "waiting_input" }
  | { kind: "cancelling" }
  | { kind: "recovering" }
  | { kind: "completed" }
  | { kind: "cancelled" }
  | { kind: "retryable_failure"; failure: TurnFailure }
  | { kind: "terminal_failure"; failure: TurnFailure };

export type TurnPrimaryAction =
  | "none"
  | "cancel"
  | "answer"
  | "reconnect"
  | "regenerate"
  | "details";

export interface TurnStateInput {
  status?: unknown;
  queryState?: unknown;
  transport?: TurnTransportState;
  cancellationRequested?: boolean;
  error?: AppError | null;
  errorCode?: unknown;
  errorMessage?: unknown;
  retryable?: unknown;
}

const TURN_STATUSES = new Set<TurnStatus>([
  "queued",
  "running",
  "waiting_input",
  "completed",
  "failed",
  "cancelled",
]);
const QUERY_STATES = new Set<TurnQueryState>([
  "queued",
  "running",
  "waiting_input",
  "recovering",
  "completed",
  "failed",
  "cancelled",
]);

function statusOf(value: unknown): TurnStatus | undefined {
  return typeof value === "string" && TURN_STATUSES.has(value as TurnStatus)
    ? (value as TurnStatus)
    : undefined;
}

function queryStateOf(value: unknown): TurnQueryState | undefined {
  return typeof value === "string" && QUERY_STATES.has(value as TurnQueryState)
    ? (value as TurnQueryState)
    : undefined;
}

export function turnViewState(input: TurnStateInput): TurnViewState {
  const queryState = queryStateOf(input.queryState);
  const status =
    statusOf(input.status) ??
    (queryState === "recovering" ? undefined : queryState);

  if (status === "completed") return { kind: "completed" };
  if (status === "cancelled") return { kind: "cancelled" };
  if (status === "failed") {
    const failure = normalizeTurnFailure(input);
    return failure.retryable
      ? { kind: "retryable_failure", failure }
      : { kind: "terminal_failure", failure };
  }
  if (input.cancellationRequested && status) return { kind: "cancelling" };
  if (
    queryState === "recovering" ||
    input.transport === "recovering" ||
    input.transport === "offline"
  ) {
    return status || queryState === "recovering"
      ? { kind: "recovering" }
      : { kind: "idle" };
  }
  if (input.transport === "connecting" && !status)
    return { kind: "connecting" };
  if (status === "queued") return { kind: "queued" };
  if (status === "running") return { kind: "running" };
  if (status === "waiting_input") return { kind: "waiting_input" };
  return { kind: "idle" };
}

export function turnPrimaryAction(state: TurnViewState): TurnPrimaryAction {
  switch (state.kind) {
    case "queued":
    case "running":
      return "cancel";
    case "waiting_input":
      return "answer";
    case "recovering":
      return "reconnect";
    case "retryable_failure":
      return "regenerate";
    case "terminal_failure":
      return "details";
    default:
      return "none";
  }
}

export function turnStateMessageKey(state: TurnViewState): string {
  return `chat.turn.status.${state.kind}`;
}
