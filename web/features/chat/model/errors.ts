import type { TurnFailureCode } from "@/contracts/generated/turn-protocol";
import type { AppError } from "@/shared/api/errors";

const FAILURE_CODES = new Set<TurnFailureCode>([
  "worker_lost",
  "lease_lost",
  "coordination_unavailable",
  "provider_error",
  "internal_error",
  "rejected",
  "server_shutdown",
]);

export interface TurnFailure {
  code: TurnFailureCode | "unknown";
  message: string;
  retryable: boolean;
}

export function normalizeTurnFailure(input: {
  error?: AppError | null;
  errorCode?: unknown;
  errorMessage?: unknown;
  retryable?: unknown;
}): TurnFailure {
  const candidate = input.error?.code ?? input.errorCode;
  const code =
    typeof candidate === "string" &&
    FAILURE_CODES.has(candidate as TurnFailureCode)
      ? (candidate as TurnFailureCode)
      : "unknown";
  return {
    code,
    message:
      input.error?.message ??
      (typeof input.errorMessage === "string"
        ? input.errorMessage
        : "Turn failed"),
    retryable:
      input.error?.retryable ??
      (typeof input.retryable === "boolean"
        ? input.retryable
        : code === "worker_lost" ||
          code === "lease_lost" ||
          code === "server_shutdown"),
  };
}
