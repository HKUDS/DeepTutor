import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { shouldPollGitHubCopilotAuth } from "../lib/github-copilot-auth";

const EDITOR = path.resolve(
  process.cwd(),
  "components/settings/ServiceConfigEditor.tsx",
);
const WORKSPACE = path.resolve(
  process.cwd(),
  "components/settings/ProvidersWorkspace.tsx",
);
const CARD = path.resolve(
  process.cwd(),
  "components/settings/GitHubCopilotAuthCard.tsx",
);
const EN = path.resolve(process.cwd(), "locales/en/app.json");
const ZH = path.resolve(process.cwd(), "locales/zh/app.json");

test("GitHub Copilot renders a Device Flow login card in both settings surfaces", () => {
  const editor = readFileSync(EDITOR, "utf8");
  const workspace = readFileSync(WORKSPACE, "utf8");
  const card = readFileSync(CARD, "utf8");

  assert.match(editor, /providerValue === "github_copilot"/);
  assert.match(editor, /<GitHubCopilotAuthCard/);
  assert.match(workspace, /source\.provider === "github_copilot"/);
  assert.match(workspace, /<GitHubCopilotAuthCard/);
  assert.match(card, /startGitHubCopilotLogin/);
  assert.match(card, /cancelGitHubCopilotLogin/);
  assert.match(card, /logoutGitHubCopilot/);
});

test("GitHub Copilot auth polling only runs while device authorization is waiting", () => {
  const base = {
    connection: "authorizing" as const,
    operation_state: "waiting" as const,
    verification_uri: "https://github.com/login/device",
    user_code: "ABCD-1234",
    expires_at: 2_000_000_000,
    account_id: null,
    error_code: null,
  };

  assert.equal(shouldPollGitHubCopilotAuth(base), true);
  assert.equal(
    shouldPollGitHubCopilotAuth({
      ...base,
      connection: "connected",
      operation_state: "completed",
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: "octocat",
    }),
    false,
  );
  assert.equal(
    shouldPollGitHubCopilotAuth({
      ...base,
      connection: "disconnected",
      operation_state: "cancelled",
      verification_uri: null,
      user_code: null,
      expires_at: null,
    }),
    false,
  );
});

test("GitHub Copilot auth copy stays in sync across locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, unknown>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, unknown>;
  const keys = (locale: Record<string, unknown>) =>
    Object.keys(locale)
      .filter((key) => key.startsWith("githubCopilot.auth."))
      .sort();

  assert.ok(keys(en).length >= 15);
  assert.deepEqual(keys(en), keys(zh));
  for (const key of keys(en)) {
    assert.equal(typeof en[key], "string");
    assert.equal(typeof zh[key], "string");
  }
});
