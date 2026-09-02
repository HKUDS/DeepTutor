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

test("LLM profiles expose wire API selection only when provider metadata supports it", () => {
  const editor = readFileSync(EDITOR, "utf8");
  const context = readFileSync(CONTEXT, "utf8");

  assert.match(context, /supports_wire_api_selection\?: boolean/);
  assert.match(editor, /providerOption\?\.supports_wire_api_selection/);
  assert.match(editor, /updateProfileField\(service, "wire_api"/);
  assert.match(editor, /t\("API protocol"\)/);
  assert.match(editor, /value="responses"/);
  assert.match(editor, /value="chat_completions"/);
});

test("wire API settings copy stays in sync across locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, unknown>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, unknown>;
  const keys = [
    "API protocol",
    "Auto (recommended)",
    "Responses API",
    "Chat Completions",
    "Automatically select the protocol and fall back when supported.",
    "Require the Responses API. Endpoint errors are returned without falling back.",
    "Require the Chat Completions API.",
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
