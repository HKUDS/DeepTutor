export type RuntimeHealth =
  | "healthy"
  | "degraded"
  | "recovering"
  | "unavailable";

export interface RuntimeStatusModel {
  workerId: string;
  workerCount: number;
  coordinationMode: "memory" | "redis";
  redisConfigured: boolean;
  redisStatus: "ok" | "unavailable" | "not_configured";
  leaderId: string | null;
  leaderHealthy: boolean | null;
  ownerTurnCount: number;
  recoveryBacklog: number;
  leaseTtlSeconds: number;
  renewIntervalSeconds: number;
  recoveryIntervalSeconds: number;
  protocolVersion: string;
  minimumWebProtocolVersion: string;
}

export interface RuntimeStatusSnapshot {
  data: RuntimeStatusModel | null;
  health: RuntimeHealth;
  error: string | null;
  loading: boolean;
  lastUpdated: number | null;
}

const SECRET_KEY =
  /(?:password|passwd|secret|token|credential|api[_-]?key|redis[_-]?url|dsn)/i;

export class UnsafeRuntimePayloadError extends Error {
  constructor() {
    super("Runtime status contained a credential-like field");
    this.name = "UnsafeRuntimePayloadError";
  }
}

function hasCredentialLikeKey(
  value: unknown,
  seen = new Set<object>(),
): boolean {
  if (!value || typeof value !== "object") return false;
  if (seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value))
    return value.some((item) => hasCredentialLikeKey(item, seen));
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (SECRET_KEY.test(key)) return true;
    if (hasCredentialLikeKey(child, seen)) return true;
  }
  return false;
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Runtime status must be an object");
  }
  return value as Record<string, unknown>;
}

function integer(value: unknown, field: string, minimum = 0): number {
  if (!Number.isInteger(value) || Number(value) < minimum) {
    throw new TypeError(`Runtime status field ${field} is invalid`);
  }
  return Number(value);
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`Runtime status field ${field} is invalid`);
  }
  return value.trim();
}

export function parseRuntimeStatus(raw: unknown): RuntimeStatusModel {
  if (hasCredentialLikeKey(raw)) throw new UnsafeRuntimePayloadError();
  const envelope = record(raw);
  const source = record(envelope.runtime_status ?? envelope);
  const coordinationMode = source.coordination_mode;
  const redisStatus = source.redis_status;
  if (coordinationMode !== "memory" && coordinationMode !== "redis") {
    throw new TypeError("Runtime coordination mode is invalid");
  }
  if (
    redisStatus !== "ok" &&
    redisStatus !== "unavailable" &&
    redisStatus !== "not_configured"
  ) {
    throw new TypeError("Runtime Redis status is invalid");
  }
  if (typeof source.redis_configured !== "boolean") {
    throw new TypeError("Runtime Redis configuration flag is invalid");
  }
  if (
    source.leader_healthy !== null &&
    source.leader_healthy !== undefined &&
    typeof source.leader_healthy !== "boolean"
  ) {
    throw new TypeError("Runtime leader health is invalid");
  }

  return {
    workerId: text(source.worker_id, "worker_id"),
    workerCount: integer(source.worker_count, "worker_count", 1),
    coordinationMode,
    redisConfigured: source.redis_configured,
    redisStatus,
    leaderId:
      source.leader_id == null ? null : text(source.leader_id, "leader_id"),
    leaderHealthy: source.leader_healthy == null ? null : source.leader_healthy,
    ownerTurnCount: integer(source.owner_turn_count ?? 0, "owner_turn_count"),
    recoveryBacklog: integer(source.recovery_backlog ?? 0, "recovery_backlog"),
    leaseTtlSeconds: integer(source.lease_ttl_seconds, "lease_ttl_seconds", 1),
    renewIntervalSeconds: integer(
      source.renew_interval_seconds,
      "renew_interval_seconds",
      1,
    ),
    recoveryIntervalSeconds: integer(
      source.recovery_interval_seconds,
      "recovery_interval_seconds",
      1,
    ),
    protocolVersion: text(source.protocol_version ?? "2.0", "protocol_version"),
    minimumWebProtocolVersion: text(
      source.minimum_web_protocol_version ?? "2.0",
      "minimum_web_protocol_version",
    ),
  };
}

export function runtimeHealth(
  status: RuntimeStatusModel | null,
): RuntimeHealth {
  if (!status) return "unavailable";
  if (status.recoveryBacklog > 0) return "recovering";
  const redisRequired =
    status.workerCount > 1 || status.coordinationMode === "redis";
  if (
    (redisRequired &&
      (!status.redisConfigured || status.redisStatus !== "ok")) ||
    status.leaderHealthy === false
  ) {
    return "degraded";
  }
  return "healthy";
}

export interface TurnCoordinationDraft {
  backendWorkers: number;
  coordinationMode: "memory" | "redis";
  developmentReload: boolean;
  leaseTtlSeconds: number;
  recoveryIntervalSeconds: number;
}

export function validateTurnCoordination(
  draft: TurnCoordinationDraft,
  redisConfigured: boolean,
): string[] {
  const errors: string[] = [];
  if (
    !Number.isInteger(draft.backendWorkers) ||
    draft.backendWorkers < 1 ||
    draft.backendWorkers > 32
  ) {
    errors.push("Worker count must be between 1 and 32.");
  }
  if (draft.backendWorkers > 1 && draft.coordinationMode !== "redis") {
    errors.push("Multiple workers require Redis coordination.");
  }
  if (draft.backendWorkers > 1 && !redisConfigured) {
    errors.push("Configure Redis before enabling multiple workers.");
  }
  if (draft.backendWorkers > 1 && draft.developmentReload) {
    errors.push("Development reload and multiple workers cannot run together.");
  }
  if (
    !Number.isInteger(draft.leaseTtlSeconds) ||
    draft.leaseTtlSeconds < 5 ||
    draft.leaseTtlSeconds > 300
  ) {
    errors.push("Lease TTL must be between 5 and 300 seconds.");
  }
  if (
    !Number.isInteger(draft.recoveryIntervalSeconds) ||
    draft.recoveryIntervalSeconds < 1 ||
    draft.recoveryIntervalSeconds > 60
  ) {
    errors.push("Recovery interval must be between 1 and 60 seconds.");
  }
  return errors;
}
