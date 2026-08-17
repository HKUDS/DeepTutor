import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { createInstance } from "i18next";

import {
  CODEX_MANAGED_BY,
  isBoundManagedCodexProfile,
} from "../components/settings/codex-profile";

const EDITOR = path.resolve(
  process.cwd(),
  "components/settings/ServiceConfigEditor.tsx",
);
const CARD = path.resolve(
  process.cwd(),
  "components/settings/CodexOAuthCard.tsx",
);
const CLIENT = path.resolve(process.cwd(), "lib/codex-oauth.ts");
const HELPER = path.resolve(
  process.cwd(),
  "components/settings/codex-profile.ts",
);
const EN = path.resolve(process.cwd(), "locales/en/app.json");
const ZH = path.resolve(process.cwd(), "locales/zh/app.json");

test("Codex OAuth profile renders the OAuth card from provider metadata", () => {
  const source = readFileSync(EDITOR, "utf8");

  assert.match(source, /isCodexOAuthProfile\(/);
  assert.match(source, /<CodexOAuthCard/);
  assert.match(readFileSync(HELPER, "utf8"), /auth_mode === "oauth"/);
});

test("the Codex profile predicates live in one place", () => {
  const source = readFileSync(EDITOR, "utf8");

  // Duplicating the tag comparison per component is how the two copies of this
  // check drifted before; the editor must go through the shared helper.
  assert.equal(source.includes('=== "openai_codex_oauth"'), false);
  assert.match(
    readFileSync(HELPER, "utf8"),
    /CODEX_MANAGED_BY = "openai_codex_oauth"/,
  );
});

test("managed Codex reasoning controls require a current account binding", () => {
  const editor = readFileSync(EDITOR, "utf8");

  assert.equal(
    isBoundManagedCodexProfile({
      managed_by: CODEX_MANAGED_BY,
      codex_account_binding: "account-binding",
    }),
    true,
  );
  assert.equal(
    isBoundManagedCodexProfile({ managed_by: CODEX_MANAGED_BY }),
    false,
  );
  assert.match(editor, /isBoundManagedCodexProfile\(activeProfile\)/);
});

test("managed Codex profiles expose only provider-supported reasoning effort", () => {
  const source = readFileSync(EDITOR, "utf8");

  assert.match(source, /isManagedCodexProfile\(/);
  assert.match(source, /disabled=\{isManagedCodex\}/);
  assert.match(source, /!isCodexOAuth/);
  assert.match(source, /activeModel\.codex_supported_reasoning_levels/);
  assert.match(source, /!isCodexOAuth \|\| isBoundManagedCodex/);
});

test("ordinary users can edit only their owner-scoped Codex reasoning overrides", () => {
  const card = readFileSync(CARD, "utf8");
  const client = readFileSync(CLIENT, "utf8");

  assert.match(client, /models: CodexReasoningModel\[\]/);
  assert.match(card, /catalogEditable === false/);
  assert.match(card, /status\.models\.map\(\(model\)/);
  assert.match(
    card,
    /reasoningEffortOptionsFromSupportedLevels\(\s*model\.supported_reasoning_levels/,
  );
  assert.match(
    card,
    /setCodexReasoningEffort\(\s*model\.model,\s*value \|\| null,?\s*\)/,
  );
});

test("Codex OAuth copy stays in sync across locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, unknown>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, unknown>;
  const codexKeys = (locale: Record<string, unknown>) =>
    Object.keys(locale)
      .filter((key) => key.startsWith("codex.oauth."))
      .sort();

  assert.deepEqual(codexKeys(en), codexKeys(zh));
  for (const key of [
    "codex.oauth.signIn",
    "codex.oauth.ownerBound",
    "codex.oauth.remoteTitle",
    "codex.oauth.remoteSteps",
    "codex.oauth.callbackAddress",
    "codex.oauth.copyCommand",
    "codex.oauth.commandCopied",
    "codex.oauth.copyFailed",
    "codex.oauth.openAuthorization",
    "codex.oauth.expiresIn",
    "codex.oauth.callbackMissing",
    "codex.oauth.callbackMissingUnknown",
    "codex.oauth.callbackUnavailable",
    "codex.oauth.invalidResponse",
    "codex.oauth.reasoningTitle",
    "codex.oauth.reasoningDescription",
    "codex.oauth.reasoningSaved",
    "codex.oauth.reasoningUnsupported",
    "codex.oauth.reasoningCatalogChanged",
  ]) {
    assert.ok(codexKeys(en).includes(key));
    assert.equal(typeof en[key], "string");
    assert.equal(typeof zh[key], "string");
  }
  for (const key of codexKeys(en)) {
    assert.equal(typeof en[key], "string");
    assert.equal(typeof zh[key], "string");
  }
});

test("Codex OAuth callback copy interpolates real ports and has a safe unknown-port fallback", async () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, string>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, string>;
  const i18n = createInstance();
  await i18n.init({
    lng: "en",
    fallbackLng: false,
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
  });

  for (const locale of ["en", "zh"]) {
    await i18n.changeLanguage(locale);
    assert.match(
      i18n.t("codex.oauth.callbackMissing", { port: 1457 }),
      /localhost:1457/,
    );
    const fallback = i18n.t("codex.oauth.callbackMissingUnknown");
    assert.notEqual(fallback, "codex.oauth.callbackMissingUnknown");
    assert.equal(fallback.includes("{{port}}"), false);
    assert.equal(fallback.includes("localhost:"), false);
    assert.equal(fallback.includes("SSH"), false);
    assert.equal(fallback.includes("隧道"), false);
    assert.match(i18n.t("codex.oauth.expiresIn", { seconds: 42 }), /42/);
  }
});
