import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  codexStatusMessageKey,
  shouldPollCodexStatus,
  type CodexOAuthStatus,
} from "../lib/codex-oauth";

const CODEX_CLIENT = path.resolve(process.cwd(), "lib/codex-oauth.ts");
const CODEX_CARD = path.resolve(
  process.cwd(),
  "components/settings/CodexOAuthCard.tsx",
);

function status(
  overrides: Partial<CodexOAuthStatus> = {},
): CodexOAuthStatus {
  return {
    connection: "disconnected",
    operation_id: null,
    operation_state: null,
    model_count: 0,
    catalog_source: null,
    catalog_fetched_at: null,
    active_model: null,
    auto_switched: false,
    sol_available: false,
    error_code: null,
    ...overrides,
  };
}

test("Codex terminal operation states stop polling", () => {
  for (const operation_state of [
    "completed",
    "cancelled",
    "expired",
    "failed",
  ] as const) {
    assert.equal(
      shouldPollCodexStatus(status({ operation_state })),
      false,
    );
  }
  for (const operation_state of [
    "waiting",
    "exchanging",
    "fetching_models",
  ] as const) {
    assert.equal(shouldPollCodexStatus(status({ operation_state })), true);
  }
});

test("Codex public client types contain no secret fields", () => {
  const source = readFileSync(CODEX_CLIENT, "utf8");

  for (const forbidden of [
    "access_token",
    "refresh_token",
    "account_id",
    "email",
  ]) {
    assert.equal(source.includes(forbidden), false);
  }
});

test("Sol missing message preserves the current model", () => {
  assert.equal(
    codexStatusMessageKey(
      status({ connection: "connected", sol_available: false }),
    ),
    "codex.oauth.solMissing",
  );
});

test("Codex error codes map to stable translation keys", () => {
  assert.equal(
    codexStatusMessageKey(
      status({
        connection: "error",
        operation_state: "failed",
        error_code: "catalog_unavailable",
      }),
    ),
    "codex.oauth.catalogFailed",
  );
  assert.equal(
    codexStatusMessageKey(
      status({ error_code: "inference_in_progress" }),
    ),
    "codex.oauth.inferenceActive",
  );
});

test("Codex sign-in opens its browser window before awaiting the API", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const signIn = source.slice(
    source.indexOf("const signIn"),
    source.indexOf("const cancel"),
  );

  assert.ok(signIn.indexOf("window.open(") < signIn.indexOf("await startCodexLogin()"));
});
