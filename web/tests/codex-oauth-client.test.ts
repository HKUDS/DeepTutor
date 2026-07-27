import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  buildSshForwardCommand,
  CodexOAuthApiError,
  codexStatusMessageKey,
  isLoopbackHostname,
  requestCodex,
  shouldPollCodexStatus,
  type CodexLoginStart,
  type CodexOAuthStatus,
} from "../lib/codex-oauth";

const CODEX_CLIENT = path.resolve(process.cwd(), "lib/codex-oauth.ts");
const CODEX_CARD = path.resolve(
  process.cwd(),
  "components/settings/CodexOAuthCard.tsx",
);

function status(overrides: Partial<CodexOAuthStatus> = {}): CodexOAuthStatus {
  return {
    connection: "disconnected",
    operation_id: null,
    operation_state: null,
    callback_port: null,
    redirect_uri: null,
    model_count: 0,
    catalog_source: null,
    catalog_fetched_at: null,
    active_model: null,
    activated: false,
    error_code: null,
    ...overrides,
  };
}

test("Codex OAuth response types expose remote-login guidance", () => {
  const login: CodexLoginStart = {
    operation_id: "operation-1",
    authorize_url: "https://auth.example.com",
    expires_in: 300,
    callback_port: 1457,
    redirect_uri: "http://localhost:1457/auth/callback",
    ssh_forward_command:
      "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@deeptutor.example.com",
  };
  const current = status({
    callback_port: 1457,
    redirect_uri: "http://localhost:1457/auth/callback",
  });

  assert.equal(login.callback_port, 1457);
  assert.equal(
    login.ssh_forward_command,
    "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@deeptutor.example.com",
  );
  assert.equal(current.redirect_uri, "http://localhost:1457/auth/callback");
});

test("Codex OAuth recognizes loopback hostnames", () => {
  for (const hostname of [
    "localhost",
    "app.localhost",
    "127.0.0.1",
    "127.12.34.56",
    "::1",
    "[::1]",
  ]) {
    assert.equal(isLoopbackHostname(hostname), true, hostname);
  }

  for (const hostname of [
    "192.168.1.10",
    "deeptutor.example.com",
    "10.0.0.8",
    "127.0.0.256",
    "127.12.999.56",
    "127.1.2.-1",
    "127.1.2",
    "127.1.2.3.4",
  ]) {
    assert.equal(isLoopbackHostname(hostname), false, hostname);
  }
});

test("Codex OAuth builds SSH forwarding guidance for the current server", () => {
  assert.equal(
    buildSshForwardCommand(1457, "deeptutor.example.com"),
    "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@deeptutor.example.com",
  );
  assert.equal(
    buildSshForwardCommand(1457, ""),
    "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@<server-host>",
  );
});

test("Codex OAuth reports a stable error for an invalid successful response", async () => {
  const responseBody = "<!doctype html><title>Proxy error</title>";
  const fetchImpl = async (): Promise<Response> =>
    new Response(responseBody, {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });

  await assert.rejects(
    requestCodex("/oauth/status", "GET", fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof CodexOAuthApiError);
      assert.equal(error.code, "invalid_response");
      assert.equal(
        error.message,
        "DeepTutor returned an invalid Codex OAuth response.",
      );
      assert.equal(error.message.includes(responseBody), false);
      assert.equal(error.message.includes("text/html"), false);
      return true;
    },
  );
});

test("Codex OAuth preserves structured errors from non-successful responses", async () => {
  const fetchImpl = async (): Promise<Response> =>
    new Response(
      JSON.stringify({
        detail: { code: "login_timeout", message: "Login timed out." },
      }),
      {
        status: 408,
        headers: { "content-type": "application/json" },
      },
    );

  await assert.rejects(
    requestCodex("/oauth/status", "GET", fetchImpl),
    (error: unknown) => {
      assert.ok(error instanceof CodexOAuthApiError);
      assert.equal(error.code, "login_timeout");
      assert.equal(error.message, "Login timed out.");
      return true;
    },
  );
});

test("Codex terminal operation states stop polling", () => {
  for (const operation_state of [
    "completed",
    "cancelled",
    "expired",
    "failed",
  ] as const) {
    assert.equal(shouldPollCodexStatus(status({ operation_state })), false);
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

test("A connected account reports connected regardless of which models it has", () => {
  assert.equal(
    codexStatusMessageKey(status({ connection: "connected" })),
    "codex.oauth.connected",
  );
  assert.equal(
    codexStatusMessageKey(
      status({
        connection: "connected",
        activated: true,
        active_model: "gpt-5.6-sol",
      }),
    ),
    "codex.oauth.activated",
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
    codexStatusMessageKey(status({ error_code: "inference_in_progress" })),
    "codex.oauth.inferenceActive",
  );
});

test("Codex sign-in opens its browser window before awaiting the API", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const signIn = source.slice(
    source.indexOf("const signIn"),
    source.indexOf("const cancel"),
  );

  assert.ok(
    signIn.indexOf("window.open(") < signIn.indexOf("await startCodexLogin()"),
  );
});
