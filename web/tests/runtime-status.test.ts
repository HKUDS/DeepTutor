import assert from "node:assert/strict";
import test from "node:test";
import {
  parseRuntimeStatus,
  runtimeHealth,
  UnsafeRuntimePayloadError,
  validateTurnCoordination,
} from "../features/runtime-status/model";

const healthyPayload = {
  worker_id: "worker-a",
  worker_count: 4,
  coordination_mode: "redis",
  redis_configured: true,
  redis_status: "ok",
  leader_id: "worker-b",
  leader_healthy: true,
  owner_turn_count: 3,
  recovery_backlog: 0,
  lease_ttl_seconds: 30,
  renew_interval_seconds: 10,
  recovery_interval_seconds: 5,
  protocol_version: "2.0",
  minimum_web_protocol_version: "2.0",
};

test("runtime status parses only the public operational contract", () => {
  const status = parseRuntimeStatus({
    runtime_status: healthyPayload,
    harmless_extra: true,
  });
  assert.deepEqual(status, {
    workerId: "worker-a",
    workerCount: 4,
    coordinationMode: "redis",
    redisConfigured: true,
    redisStatus: "ok",
    leaderId: "worker-b",
    leaderHealthy: true,
    ownerTurnCount: 3,
    recoveryBacklog: 0,
    leaseTtlSeconds: 30,
    renewIntervalSeconds: 10,
    recoveryIntervalSeconds: 5,
    protocolVersion: "2.0",
    minimumWebProtocolVersion: "2.0",
  });
});

test("credential-like keys reject the entire runtime payload", () => {
  for (const secret of [
    { redis_url: "redis://user:password@host" },
    { nested: { password: "value" } },
    { apiToken: "value" },
    { credentials: { value: "secret" } },
  ]) {
    assert.throws(
      () => parseRuntimeStatus({ ...healthyPayload, ...secret }),
      UnsafeRuntimePayloadError,
    );
  }
});

test("health prioritizes recovery, then coordination failures", () => {
  const healthy = parseRuntimeStatus(healthyPayload);
  assert.equal(runtimeHealth(healthy), "healthy");
  assert.equal(runtimeHealth({ ...healthy, recoveryBacklog: 2 }), "recovering");
  assert.equal(
    runtimeHealth({ ...healthy, redisStatus: "unavailable" }),
    "degraded",
  );
  assert.equal(runtimeHealth({ ...healthy, leaderHealthy: false }), "degraded");
  assert.equal(runtimeHealth(null), "unavailable");
});

test("multi-worker validation requires Redis and disables development reload", () => {
  const errors = validateTurnCoordination(
    {
      backendWorkers: 4,
      coordinationMode: "memory",
      developmentReload: true,
      leaseTtlSeconds: 2,
      recoveryIntervalSeconds: 90,
    },
    false,
  );
  assert.deepEqual(errors, [
    "Multiple workers require Redis coordination.",
    "Configure Redis before enabling multiple workers.",
    "Development reload and multiple workers cannot run together.",
    "Lease TTL must be between 5 and 300 seconds.",
    "Recovery interval must be between 1 and 60 seconds.",
  ]);
});
