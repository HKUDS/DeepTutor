import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

let mockLocalStorage: Record<string, string> = {};
let mockSessionStorage: Record<string, string> = {};

function mockWindow() {
  global.window = {
    localStorage: {
      getItem: (key: string) => mockLocalStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockLocalStorage[key] = value;
      },
      removeItem: (key: string) => {
        delete mockLocalStorage[key];
      },
    },
    sessionStorage: {
      getItem: (key: string) => mockSessionStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockSessionStorage[key] = value;
      },
      removeItem: (key: string) => {
        delete mockSessionStorage[key];
      },
    },
    dispatchEvent: () => true,
  } as any;
}

mockWindow();

import * as settingsContext from "../components/settings/SettingsContext";

const settingsContextPath = path.join(
  process.cwd(),
  "components",
  "settings",
  "SettingsContext.tsx",
);

function readSettingsContextSource() {
  return fs.readFileSync(settingsContextPath, "utf8");
}

test("settings-protocol: LLM_API_PROTOCOL_VALUES exposes auto + the three selectable protocols", () => {
  const values = (settingsContext as any).LLM_API_PROTOCOL_VALUES;
  assert.deepEqual(values, [
    "auto",
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
  ]);
});

test("settings-protocol: EXPLICIT_LLM_API_PROTOCOL_VALUES excludes auto for new/edit flow", () => {
  const values = (settingsContext as any).EXPLICIT_LLM_API_PROTOCOL_VALUES;
  assert.deepEqual(values, [
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
  ]);
  assert.ok(!values.includes("auto"), "auto must not be a new/edit choice");
});

test("settings-protocol: defaultLlmProtocol returns an explicit protocol for new profiles", () => {
  const fn = (settingsContext as any).defaultLlmProtocol;
  assert.equal(typeof fn, "function");
  assert.equal(fn("anthropic", "Anthropic"), "anthropic_messages");
  assert.equal(fn("custom_anthropic", "Custom (Anthropic API)"), "anthropic_messages");
  assert.equal(fn("openai", "OpenAI"), "openai_chat_completions");
  assert.equal(fn("custom", undefined), "openai_chat_completions");
  // The default is never `auto` — that value is reserved for legacy migration.
  assert.notEqual(fn("openai", "OpenAI"), "auto");
});

test("settings-protocol: CatalogProfile carries the protocol contract fields", () => {
  const source = readSettingsContextSource();
  for (const field of [
    "api_protocol",
    "strict_protocol",
    "api_key_set",
    "capability_probe_status",
  ]) {
    assert.match(
      source,
      new RegExp(`${field}\\??:`),
      `CatalogProfile should declare ${field}`,
    );
  }
});

test("settings-protocol: addProfile sets an explicit api_protocol for LLM profiles", () => {
  const source = readSettingsContextSource();
  assert.match(
    source,
    /api_protocol:\s*defaultLlmProtocol\(/,
    "addProfile should seed a new LLM profile with an explicit protocol",
  );
  assert.match(
    source,
    /api_key_set:\s*false/,
    "addProfile should mark the secret as unset",
  );
});

test("settings-protocol: updateProfileBoolField and updateProfileApiKey exist", () => {
  const source = readSettingsContextSource();
  assert.match(
    source,
    /const updateProfileBoolField = useCallback/,
    "SettingsContext should expose a boolean profile-field setter",
  );
  assert.match(
    source,
    /const updateProfileApiKey = useCallback/,
    "SettingsContext should expose a tri-state api-key setter",
  );
  assert.match(
    source,
    /api_key_set = Boolean\(value\.trim\(\)\)/,
    "typing a value should mark the secret as set",
  );
});

test("settings-protocol: editor offers only the three explicit protocols", () => {
  const editorPath = path.join(
    process.cwd(),
    "components",
    "settings",
    "ServiceConfigEditor.tsx",
  );
  const source = fs.readFileSync(editorPath, "utf8");
  assert.match(
    source,
    /t\("API Protocol"\)/,
    "ServiceConfigEditor should label the protocol selector via i18n",
  );
  assert.match(
    source,
    /t\("Strict protocol"\)/,
    "ServiceConfigEditor should label the strict-protocol toggle via i18n",
  );
  // The new/edit flow must never offer `auto` as a selectable choice — only
  // the three explicit protocols are selectable options.
  assert.match(
    source,
    /EXPLICIT_LLM_API_PROTOCOL_VALUES/,
    "ServiceConfigEditor should derive the selectable choices from the explicit protocol list",
  );
  assert.match(
    source,
    /protocolOptions\.length > 0[\s\S]*?\? protocolOptions/,
    "ServiceConfigEditor should use the backend-provided explicit protocol options",
  );
  assert.doesNotMatch(
    source,
    /\bLLM_API_PROTOCOL_VALUES\.map/,
    "ServiceConfigEditor must not offer `auto` as a normal option",
  );
});

test("settings-protocol: legacy auto renders as a disabled compatibility state", () => {
  const editorPath = path.join(
    process.cwd(),
    "components",
    "settings",
    "ServiceConfigEditor.tsx",
  );
  const source = fs.readFileSync(editorPath, "utf8");
  // A legacy profile still on `auto` renders that value as a disabled option,
  // so the state survives a save without being a normal new/edit choice.
  assert.match(
    source,
    /value="auto"\s*\n?\s*disabled/,
    "the legacy auto option must be disabled (compatibility state, not a choice)",
  );
  assert.match(
    source,
    /t\("Auto \(compatibility\)"\)/,
    "the legacy auto state should use the compatibility label",
  );
  assert.match(
    source,
    /\(profile\.api_protocol \|\| "auto"\) === "auto"/,
    "the disabled auto option should only appear for a legacy auto profile",
  );
});
