import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const EDITOR = path.resolve(
  process.cwd(),
  "components/settings/ServiceConfigEditor.tsx",
);
const CONTEXT = path.resolve(
  process.cwd(),
  "features/settings/store/SettingsStore.tsx",
);
const MAIN = path.resolve(
  process.cwd(),
  "components/settings/SettingsMain.tsx",
);
const TOOLBAR = path.resolve(
  process.cwd(),
  "components/settings/SettingsToolbar.tsx",
);
const EN = path.resolve(process.cwd(), "locales/en/app.json");
const ZH = path.resolve(process.cwd(), "locales/zh/app.json");

test("LLM-shaped profiles expose API formats supplied by provider metadata", () => {
  const editor = readFileSync(EDITOR, "utf8");
  const context = readFileSync(CONTEXT, "utf8");

  assert.match(context, /api_formats\?: string\[\]/);
  assert.match(editor, /providerOption\?\.api_formats/);
  assert.match(editor, /updateProfileField\(service, "api_format"/);
  assert.match(editor, /t\("API format"\)/);
  assert.match(editor, /openai_chat: "OpenAI Chat Completions"/);
  assert.match(editor, /openai_responses: "OpenAI Responses"/);
  assert.match(editor, /anthropic: "Anthropic Messages"/);
});

test("API format settings copy stays in sync across locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, unknown>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, unknown>;
  const keys = [
    "API format",
    "Auto (recommended)",
    "OpenAI Chat Completions",
    "OpenAI Responses",
    "Anthropic Messages",
    "Chat Completions for most endpoints; Responses for OpenAI reasoning models, with fallback.",
    "Send every request to /v1/chat/completions.",
    "Send every request to /v1/responses. Endpoint errors are returned without falling back.",
    "Send every request as Anthropic Messages (/v1/messages).",
  ];

  for (const key of keys) {
    assert.equal(typeof en[key], "string", `missing English copy: ${key}`);
    assert.equal(typeof zh[key], "string", `missing Chinese copy: ${key}`);
  }
});

test("wire API settings remain usable on narrow viewports", () => {
  const editor = readFileSync(EDITOR, "utf8");
  const main = readFileSync(MAIN, "utf8");
  const toolbar = readFileSync(TOOLBAR, "utf8");

  // The 1.6 settings UI uses provider cards and a modal instead of the old
  // sticky profile list. Profile fields stay one-column until the `sm`
  // breakpoint, and the shell keeps compact horizontal padding on phones.
  assert.match(editor, /grid gap-4 sm:grid-cols-2/);
  assert.match(main, /px-5[^\"]*sm:px-8/);
  assert.match(toolbar, /flex-col[^\"]*sm:flex-row/);
});
