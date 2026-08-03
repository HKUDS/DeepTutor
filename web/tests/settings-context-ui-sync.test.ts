import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

let mockLocalStorage: Record<string, string> = {};
let mockSessionStorage: Record<string, string> = {};
let dispatchedEvents: Array<{ type: string; detail: any }> = [];

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
    dispatchEvent: (event: any) => {
      dispatchedEvents.push({ type: event.type, detail: event.detail });
      return true;
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  } as any;
}

mockWindow();

import * as settingsContext from "../components/settings/SettingsContext";
import {
  CODE_BLOCK_SETTINGS_EVENT,
  readStoredCodeBlockShowLineNumbers,
  readStoredCodeBlockTheme,
  readStoredCodeBlockWrapLongLines,
} from "../context/app-shell-storage";

const settingsContextPath = path.join(
  process.cwd(),
  "components",
  "settings",
  "SettingsContext.tsx",
);

function readSettingsContextSource() {
  return fs.readFileSync(settingsContextPath, "utf8");
}

test("settings-context: syncLoadedCodeBlockSettingsToAppShell writes backend-loaded values into app-shell storage", () => {
  const sync = (settingsContext as any).syncLoadedCodeBlockSettingsToAppShell;

  assert.equal(typeof sync, "function");

  mockLocalStorage = {};
  dispatchedEvents = [];

  const normalized = sync({
    code_block_theme: "dracula",
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  });

  assert.equal(readStoredCodeBlockTheme(), "dracula");
  assert.equal(readStoredCodeBlockShowLineNumbers(), true);
  assert.equal(readStoredCodeBlockWrapLongLines(), true);
  assert.deepEqual(normalized, {
    code_block_theme: "dracula",
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  });
  assert.equal(
    dispatchedEvents.filter((event) => event.type === CODE_BLOCK_SETTINGS_EVENT)
      .length,
    3,
  );
});

test("settings-context: persistUiSettingsPatch sends only the changed code-block field", async () => {
  const persist = (settingsContext as any).persistUiSettingsPatch;

  assert.equal(typeof persist, "function");

  let capturedInput: unknown;
  let capturedInit: RequestInit | undefined;

  await persist(
    {
      code_block_theme: "dracula",
    },
    async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedInput = input;
      capturedInit = init;
      return { ok: true } as Response;
    },
  );

  assert.match(String(capturedInput), /\/api\/v1\/settings\/ui$/);
  assert.equal(capturedInit?.method, "PUT");
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), {
    code_block_theme: "dracula",
  });
});

test("settings-context: persistUiSettingsPatch can save theme without sending code-block fields", async () => {
  const persist = (settingsContext as any).persistUiSettingsPatch;

  assert.equal(typeof persist, "function");

  let capturedInit: RequestInit | undefined;

  await persist(
    {
      theme: "dark",
    },
    async (_input: RequestInfo | URL, init?: RequestInit) => {
      capturedInit = init;
      return { ok: true } as Response;
    },
  );

  assert.deepEqual(JSON.parse(String(capturedInit?.body)), {
    theme: "dark",
  });
});

test("settings-context: boolean values survive reload cycle from localStorage", () => {
  const sync = (settingsContext as any).syncLoadedCodeBlockSettingsToAppShell;

  mockLocalStorage = {};
  sync({
    code_block_theme: "dracula",
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  });

  assert.equal(readStoredCodeBlockTheme(), "dracula");
  assert.equal(readStoredCodeBlockShowLineNumbers(), true);
  assert.equal(readStoredCodeBlockWrapLongLines(), true);

  assert.equal(
    readStoredCodeBlockTheme(),
    "dracula",
    "Theme should persist across reload",
  );
  assert.equal(
    readStoredCodeBlockShowLineNumbers(),
    true,
    "Show line numbers should persist across reload",
  );
  assert.equal(
    readStoredCodeBlockWrapLongLines(),
    true,
    "Wrap long lines should persist across reload",
  );

  const secondSync = sync({
    code_block_theme: "dracula",
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  });

  assert.equal(
    secondSync.code_block_show_line_numbers,
    true,
    "Show line numbers should remain true after backend sync",
  );
  assert.equal(
    secondSync.code_block_wrap_long_lines,
    true,
    "Wrap long lines should remain true after backend sync",
  );
});

test("settings-context: syncLoadedCodeBlockSettingsToAppShell handles string boolean representations from backend", () => {
  const sync = (settingsContext as any).syncLoadedCodeBlockSettingsToAppShell;

  mockLocalStorage = {};

  const result = sync({
    code_block_theme: "dracula",
    code_block_show_line_numbers: "True",
    code_block_wrap_long_lines: "true",
  });

  assert.equal(
    result.code_block_show_line_numbers,
    true,
    "String 'True' should be normalized to boolean true",
  );
  assert.equal(
    result.code_block_wrap_long_lines,
    true,
    "String 'true' should be normalized to boolean true",
  );
  assert.equal(
    readStoredCodeBlockShowLineNumbers(),
    true,
    "Line numbers should be stored as true",
  );
  assert.equal(
    readStoredCodeBlockWrapLongLines(),
    true,
    "Wrap long lines should be stored as true",
  );
});

test("settings-context: backend values override localStorage values during sync", () => {
  const sync = (settingsContext as any).syncLoadedCodeBlockSettingsToAppShell;

  // Simulate localStorage having different (old/stale) values
  mockLocalStorage = {
    "deeptutor.codeBlockShowLineNumbers": "false",
    "deeptutor.codeBlockWrapLongLines": "false",
    "deeptutor.codeBlockTheme": "oneDark",
  };

  // Backend returns true values
  const result = sync({
    code_block_theme: "dracula",
    code_block_show_line_numbers: true,
    code_block_wrap_long_lines: true,
  });

  // Verify backend values win
  assert.equal(
    result.code_block_show_line_numbers,
    true,
    "Backend true should override localStorage false",
  );
  assert.equal(
    result.code_block_wrap_long_lines,
    true,
    "Backend true should override localStorage false",
  );
  assert.equal(
    result.code_block_theme,
    "dracula",
    "Backend theme should override localStorage theme",
  );

  // Verify localStorage is updated to backend values
  assert.equal(
    readStoredCodeBlockShowLineNumbers(),
    true,
    "localStorage should be updated to backend true",
  );
  assert.equal(
    readStoredCodeBlockWrapLongLines(),
    true,
    "localStorage should be updated to backend true",
  );
  assert.equal(
    readStoredCodeBlockTheme(),
    "dracula",
    "localStorage theme should be updated to backend value",
  );

  // This test would fail if a post-mount effect re-read from localStorage,
  // as it would overwrite the backend-loaded true values with the old false values.
});

test("settings-context: routes code-block state through the AppShell single source", () => {
  const source = readSettingsContextSource();

  assert.match(
    source,
    /useAppShell/,
    "SettingsContext should read and write code-block state via AppShellContext.",
  );
  // Backend-loaded values reach AppShell through the storage/event sync helper.
  assert.match(
    source,
    /syncLoadedCodeBlockSettingsToAppShell\(\s*payload\.ui,?\s*\)/,
    "loadSettings should push backend-loaded code-block values into the AppShell source.",
  );
  // User edits delegate to the AppShell setters (which normalize, persist to
  // localStorage, and notify consumers) rather than a local mirror.
  assert.match(
    source,
    /setAppShellCodeBlockShowLineNumbers\(next\)/,
    "updateCodeBlockShowLineNumbers should delegate to the AppShell setter.",
  );
  assert.match(
    source,
    /setAppShellCodeBlockWrapLongLines\(next\)/,
    "updateCodeBlockWrapLongLines should delegate to the AppShell setter.",
  );
});
