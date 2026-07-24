import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const EDITOR = path.resolve(
  process.cwd(),
  "components/settings/ServiceConfigEditor.tsx",
);
const EN = path.resolve(process.cwd(), "locales/en/app.json");
const ZH = path.resolve(process.cwd(), "locales/zh/app.json");

test("Codex OAuth profile renders the OAuth card from provider metadata", () => {
  const source = readFileSync(EDITOR, "utf8");

  assert.match(source, /auth_mode === "oauth"/);
  assert.match(source, /providerValue === "openai_codex"/);
  assert.match(source, /<CodexOAuthCard/);
});

test("managed Codex profiles cannot expose profile or model editing", () => {
  const source = readFileSync(EDITOR, "utf8");

  assert.match(source, /managed_by === "openai_codex_oauth"/);
  assert.match(source, /isManagedCodex/);
  assert.match(source, /disabled=\{isManagedCodex\}/);
  assert.match(source, /!isCodexOAuth/);
});

test("Codex OAuth copy exists in both locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8"));
  const zh = JSON.parse(readFileSync(ZH, "utf8"));

  for (const locale of [en, zh]) {
    assert.equal(typeof locale["codex.oauth.signIn"], "string");
    assert.equal(typeof locale["codex.oauth.solMissing"], "string");
    assert.equal(typeof locale["codex.oauth.experimental"], "string");
    assert.equal(typeof locale["codex.oauth.isolated"], "string");
  }
});
