import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  buildSshForwardCommand,
  CodexOAuthApiError,
  codexRemoteGuidance,
  codexErrorMessageKey,
  codexStatusMessageKey,
  isLoopbackHostname,
  requestCodex,
  setCodexReasoningEffort,
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
    authorize_url: null,
    expires_in: null,
    callback_port: null,
    callback_forward_port: null,
    redirect_uri: null,
    model_count: 0,
    catalog_source: null,
    catalog_fetched_at: null,
    active_model: null,
    models: [],
    activated: false,
    error_code: null,
    ...overrides,
  };
}

function waitingStatus(
  overrides: Partial<CodexOAuthStatus> = {},
): CodexOAuthStatus {
  return status({
    operation_id: "operation-1",
    operation_state: "waiting",
    authorize_url: "https://auth.example.com",
    expires_in: 275,
    callback_port: 1457,
    callback_forward_port: 4782,
    redirect_uri: "http://localhost:1457/auth/callback",
    ...overrides,
  });
}

test("Codex OAuth response types expose remote-login guidance", () => {
  const login: CodexLoginStart = {
    operation_id: "operation-1",
    authorize_url: "https://auth.example.com",
    expires_in: 300,
    callback_port: 1457,
    callback_forward_port: 4782,
    redirect_uri: "http://localhost:1457/auth/callback",
    ssh_forward_command:
      "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@deeptutor.example.com",
  };
  const current = waitingStatus();

  assert.equal(login.callback_port, 1457);
  assert.equal(login.callback_forward_port, 4782);
  assert.equal(
    login.ssh_forward_command,
    "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@deeptutor.example.com",
  );
  assert.equal(current.callback_forward_port, 4782);
  assert.equal(current.redirect_uri, "http://localhost:1457/auth/callback");
  assert.equal(current.authorize_url, "https://auth.example.com");
  assert.equal(current.expires_in, 275);
});

test("Codex remote guidance recovers from a complete waiting status", () => {
  const guidance = codexRemoteGuidance(waitingStatus(), null);

  assert.deepEqual(guidance, {
    operation_id: "operation-1",
    authorize_url: "https://auth.example.com",
    expires_in: 275,
    callback_port: 1457,
    callback_forward_port: 4782,
    redirect_uri: "http://localhost:1457/auth/callback",
  });
});

test("Codex remote guidance requires waiting state and complete operation fields", () => {
  const complete = waitingStatus();

  for (const operation_state of [
    null,
    "exchanging",
    "fetching_models",
    "completed",
    "cancelled",
    "expired",
    "failed",
  ] as const) {
    assert.equal(
      codexRemoteGuidance({ ...complete, operation_state }, null),
      null,
    );
  }
  for (const field of [
    "operation_id",
    "authorize_url",
    "expires_in",
    "callback_port",
    "callback_forward_port",
    "redirect_uri",
  ] as const) {
    assert.equal(
      codexRemoteGuidance({ ...complete, [field]: null }, null),
      null,
    );
  }
});

test("Codex remote guidance prefers status expiry and only falls back to the matching start", () => {
  const login: CodexLoginStart = {
    operation_id: "operation-1",
    authorize_url: "https://auth.example.com",
    expires_in: 300,
    callback_port: 1457,
    callback_forward_port: 4782,
    redirect_uri: "http://localhost:1457/auth/callback",
    ssh_forward_command:
      "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@deeptutor.example.com",
  };
  const waiting = waitingStatus({ expires_in: 42 });

  assert.equal(codexRemoteGuidance(waiting, login)?.expires_in, 42);
  assert.equal(
    codexRemoteGuidance({ ...waiting, expires_in: null }, login)?.expires_in,
    300,
  );
  assert.equal(
    codexRemoteGuidance(
      { ...waiting, expires_in: null },
      { ...login, operation_id: "stale-operation" },
    ),
    null,
  );
});

test("Codex OAuth recognizes loopback hostnames", () => {
  for (const hostname of [
    "localhost",
    "localhost.",
    "app.localhost",
    "app.localhost.",
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
    "deeptutor.example.com.",
    "localhost..",
    "app.localhost..",
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
    buildSshForwardCommand(1457, "deeptutor.example.com", 4782),
    "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@deeptutor.example.com",
  );
  assert.equal(
    buildSshForwardCommand(1457, "", 4782),
    "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@<server-host>",
  );
});

test("SSH forwarding source contract requires distinct callback and forward ports", () => {
  const source = readFileSync(CODEX_CLIENT, "utf8");
  const commandBuilder = componentBlock(
    source,
    "export function buildSshForwardCommand",
    "export async function requestCodex",
  );

  assert.match(
    commandBuilder,
    /callbackPort:\s*number,\s*hostname:\s*string,\s*forwardPort:\s*number,/,
  );
  assert.match(
    commandBuilder,
    /\$\{callbackPort\}:127\.0\.0\.1:\$\{forwardPort\}/,
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

test("ordinary users send a scoped Codex reasoning effort update", async () => {
  let capturedUrl = "";
  let capturedInit: RequestInit | undefined;
  const fetchImpl = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    capturedUrl = String(input);
    capturedInit = init;
    return Response.json(status({ connection: "connected" }));
  };

  await setCodexReasoningEffort("gpt-5.6-sol", "high", fetchImpl);

  assert.match(
    capturedUrl,
    /\/providers\/openai-codex\/models\/reasoning-effort$/,
  );
  assert.equal(capturedInit?.method, "POST");
  assert.equal(
    capturedInit?.headers &&
      new Headers(capturedInit.headers).get("content-type"),
    "application/json",
  );
  assert.equal(
    capturedInit?.body,
    JSON.stringify({ model: "gpt-5.6-sol", reasoning_effort: "high" }),
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
  assert.equal(
    codexErrorMessageKey("login_timeout"),
    "codex.oauth.callbackMissing",
  );
  assert.equal(
    codexErrorMessageKey("callback_unavailable"),
    "codex.oauth.callbackUnavailable",
  );
  assert.equal(
    codexErrorMessageKey("invalid_response"),
    "codex.oauth.invalidResponse",
  );
  assert.equal(
    codexErrorMessageKey("reasoning_effort_unsupported"),
    "codex.oauth.reasoningUnsupported",
  );
  for (const code of ["codex_model_not_found", "codex_catalog_unavailable"]) {
    assert.equal(
      codexErrorMessageKey(code),
      "codex.oauth.reasoningCatalogChanged",
    );
  }
});

function componentBlock(
  source: string,
  startMarker: string,
  endMarker: string,
): string {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `missing ${startMarker}`);
  assert.notEqual(end, -1, `missing ${endMarker}`);
  return source.slice(start, end);
}

test("Codex status polling waits for each request and stops state updates after cleanup", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const loadStatus = componentBlock(
    source,
    "const loadStatus",
    "useEffect(() =>",
  );
  const pollingEffect = componentBlock(
    source,
    "if (pending || !status || !shouldPollCodexStatus(status)) return;",
    "// Reloading replaces",
  );

  assert.match(
    loadStatus,
    /async \(shouldApply: \(\) => boolean = \(\) => true\)/,
  );
  assert.match(loadStatus, /!shouldApply\(\)/);
  assert.match(pollingEffect, /let cancelled = false;/);
  assert.match(pollingEffect, /await loadStatus\(\(\) => !cancelled\);/);
  assert.ok(
    pollingEffect.indexOf("await loadStatus") <
      pollingEffect.indexOf("setPollTick"),
  );
  assert.match(pollingEffect, /if \(!cancelled\) setPollTick/);
  assert.match(
    pollingEffect,
    /return \(\) => \{\s*cancelled = true;\s*window\.clearTimeout\(timer\);\s*\};/,
  );
  assert.match(pollingEffect, /}, 1_000\);/);
  assert.match(
    pollingEffect,
    /if \(\s*pending \|\|\s*!status \|\| !shouldPollCodexStatus\(status\)\s*\) return;/,
  );
  assert.match(pollingEffect, /\[loadStatus, pending, status, pollTick\]/);
});

test("Codex status request epochs reject stale responses across user actions", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const loadStatus = componentBlock(
    source,
    "const loadStatus",
    "useEffect(() =>",
  );

  assert.match(source, /const statusRequestSequence = useRef\(0\);/);
  assert.match(
    source,
    /const invalidateStatusRequests = useCallback\(\(\) => \{\s*statusRequestSequence\.current \+= 1;\s*\}, \[\]\);/,
  );
  assert.match(
    loadStatus,
    /const requestSequence = statusRequestSequence\.current;/,
  );
  assert.match(
    loadStatus,
    /requestSequence !== statusRequestSequence\.current/,
  );
  assert.ok(
    loadStatus.indexOf("requestSequence !== statusRequestSequence.current") <
      loadStatus.indexOf("recordStatus(next)"),
  );
  assert.match(
    source,
    /return \(\) => \{\s*cancelled = true;\s*invalidateStatusRequests\(\);\s*\};/,
  );

  const actionBlocks = [
    componentBlock(source, "const localSignIn", "const remoteSignIn"),
    componentBlock(source, "const remoteSignIn", "const signIn"),
    componentBlock(source, "const cancel", "const refresh"),
    componentBlock(source, "const refresh", "const logout"),
    componentBlock(source, "const logout", "const polling"),
  ];
  for (const action of actionBlocks) {
    assert.ok(
      action.indexOf("invalidateStatusRequests()") < action.indexOf("await "),
    );
  }

  for (const login of actionBlocks.slice(0, 2)) {
    assert.match(login, /await loadStatus\(\);/);
    assert.equal(login.includes("recordStatus(await getCodexStatus())"), false);
  }
  for (const [action, request] of [
    [actionBlocks[2], "cancelCodexLogin"],
    [actionBlocks[3], "refreshCodexModels"],
    [actionBlocks[4], "logoutCodex"],
  ]) {
    assert.match(
      action,
      new RegExp(
        `const nextStatus = await ${request}\\(\\);\\s*invalidateStatusRequests\\(\\);\\s*recordStatus\\(nextStatus\\);`,
      ),
    );
  }
});

test("Local Codex sign-in opens its browser window before awaiting the API", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const localSignIn = componentBlock(
    source,
    "const localSignIn",
    "const remoteSignIn",
  );

  assert.ok(
    localSignIn.indexOf('window.open("about:blank"') <
      localSignIn.indexOf("await startCodexLogin()"),
  );
  assert.match(
    localSignIn,
    /authWindow\.location\.replace\(started\.authorize_url\)/,
  );
  assert.match(
    localSignIn,
    /window\.location\.assign\(started\.authorize_url\)/,
  );
});

test("Codex sign-in detects remote browsers and retains the login start", () => {
  const source = readFileSync(CODEX_CARD, "utf8");

  assert.match(source, /isLoopbackHostname\(window\.location\.hostname\)/);
  assert.match(source, /useState<CodexLoginStart \| null>\(null\)/);
  assert.match(
    source,
    /const signIn = remoteAccess \? remoteSignIn : localSignIn;/,
  );

  const remoteSignIn = componentBlock(
    source,
    "const remoteSignIn",
    "const signIn",
  );
  assert.ok(
    remoteSignIn.indexOf("await startCodexLogin()") <
      remoteSignIn.indexOf("setLoginStart(started)"),
  );
  assert.ok(
    remoteSignIn.indexOf("setLoginStart(started)") <
      remoteSignIn.indexOf("await loadStatus()"),
  );
});

test("Remote Codex sign-in never opens or redirects the browser automatically", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const remoteSignIn = componentBlock(
    source,
    "const remoteSignIn",
    "const signIn",
  );

  assert.equal(remoteSignIn.includes("window.open("), false);
  assert.equal(remoteSignIn.includes("window.location.assign("), false);
});

test("Remote Codex guidance uses the real callback port and explicit user actions", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const current = status({ callback_port: 1457 });

  assert.equal(current.callback_port, 1457);
  assert.match(
    source,
    /const callbackPort\s*=\s*status\?\.callback_port\s*\?\?\s*loginStart\?\.callback_port/,
  );
  assert.match(
    source,
    /messageKey === "codex\.oauth\.callbackMissing"\s*&&\s*callbackPort == null/,
  );
  assert.match(
    source,
    /\?\s*"codex\.oauth\.callbackMissingUnknown"\s*:\s*messageKey/,
  );
  assert.match(
    source,
    /t\(displayMessageKey,\s*\{\s*port:\s*callbackPort,?\s*\}\s*\)/,
  );

  assert.match(
    source,
    /buildSshForwardCommand\(\s*remoteGuidance\.callback_port,\s*window\.location\.hostname,\s*remoteGuidance\.callback_forward_port,\s*\)/,
  );
  assert.match(source, /\{remoteGuidance\.redirect_uri\}/);
  assert.match(
    source,
    /const remoteGuidance = codexRemoteGuidance\(status,\s*loginStart\)/,
  );
  assert.match(
    source,
    /t\("codex\.oauth\.expiresIn",\s*\{\s*seconds:\s*remoteGuidance\.expires_in,\s*\}\)/,
  );

  const copyCommand = componentBlock(
    source,
    "const copyCommand",
    "const openAuthorization",
  );
  assert.match(copyCommand, /navigator\.clipboard\.writeText\(sshCommand\)/);
  assert.match(copyCommand, /setToast\(t\("codex\.oauth\.commandCopied"\)\)/);
  assert.match(copyCommand, /setToast\(t\("codex\.oauth\.copyFailed"\)\)/);

  const openAuthorization = componentBlock(
    source,
    "const openAuthorization",
    "const cancel",
  );
  assert.match(
    openAuthorization,
    /window\.open\(remoteGuidance\.authorize_url,\s*"_blank",\s*"noopener"\)/,
  );
});

test("Cancelling Codex sign-in clears remote guidance", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const cancel = componentBlock(source, "const cancel", "const refresh");

  assert.match(cancel, /setLoginStart\(null\)/);
});

test("Terminal Codex status clears guidance only for the matching operation", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const recordStatus = componentBlock(
    source,
    "const recordStatus",
    "const loadStatus",
  );

  for (const operationState of [
    "completed",
    "cancelled",
    "expired",
    "failed",
  ]) {
    assert.match(
      recordStatus,
      new RegExp(`nextStatus\\.operation_state === "${operationState}"`),
    );
  }
  assert.match(
    recordStatus,
    /nextStatus\.operation_id === loginStart\.operation_id/,
  );
  assert.match(recordStatus, /\? null\s*: loginStart/);
});

test("Logging out clears remote authorization guidance after success", () => {
  const source = readFileSync(CODEX_CARD, "utf8");
  const logout = componentBlock(source, "const logout", "const polling");

  assert.ok(
    logout.indexOf("recordStatus(await logoutCodex())") <
      logout.indexOf("setLoginStart(null)"),
  );
});
