import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const generatedRoot = path.resolve(process.cwd(), "contracts", "generated");

test("generated turn protocol covers the complete v2 lifecycle", () => {
  const source = fs.readFileSync(
    path.join(generatedRoot, "turn-protocol.ts"),
    "utf8",
  );

  for (const value of [
    "queued",
    "running",
    "waiting_input",
    "recovering",
    "completed",
    "failed",
    "cancelled",
    "wait_for_input",
    "worker_lost",
    "protocol_version",
    "minimum_web_protocol_version",
  ]) {
    assert.match(source, new RegExp(value));
  }
});

test("generated OpenAPI types expose backend-owned browser models", () => {
  const source = fs.readFileSync(path.join(generatedRoot, "api.ts"), "utf8");

  for (const value of [
    "TurnRequest",
    "RuntimeStatus",
    "SessionSummary",
    "ErrorEnvelope",
  ]) {
    assert.match(source, new RegExp(value));
  }
});
