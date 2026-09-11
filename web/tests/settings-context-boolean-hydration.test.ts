import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import {
  readStoredCodeBlockShowLineNumbers,
  readStoredCodeBlockWrapLongLines,
  writeStoredCodeBlockShowLineNumbers,
  writeStoredCodeBlockWrapLongLines,
} from "@/context/app-shell-storage";

const settingsContextPath = path.join(
  process.cwd(),
  "features",
  "settings",
  "store",
  "SettingsStore.tsx",
);

function readSettingsContextSource() {
  return fs.readFileSync(settingsContextPath, "utf8");
}

function mockWindow() {
  global.window = {
    localStorage: {
      getItem: (key: string) =>
        (global.window as any).localStorage._storage[key] ?? null,
      setItem: (key: string, value: string) => {
        (global.window as any).localStorage._storage[key] = value;
      },
      removeItem: (key: string) => {
        delete (global.window as any).localStorage._storage[key];
      },
    },
    dispatchEvent: () => true,
  } as any;
  (global.window as any).localStorage._storage = {};
}

test("readStoredCodeBlockShowLineNumbers returns true when localStorage has string 'true'", () => {
  mockWindow();
  writeStoredCodeBlockShowLineNumbers(true);
  assert.equal(readStoredCodeBlockShowLineNumbers(), true);
});

test("readStoredCodeBlockWrapLongLines returns true when localStorage has string 'true'", () => {
  mockWindow();
  writeStoredCodeBlockWrapLongLines(true);
  assert.equal(readStoredCodeBlockWrapLongLines(), true);
});

test("readStoredCodeBlockShowLineNumbers returns false when localStorage is undefined (SSR)", () => {
  (global.window as any) = undefined as any;
  assert.equal(
    readStoredCodeBlockShowLineNumbers(),
    false,
    "Should return default false when window is undefined",
  );
});

test("readStoredCodeBlockWrapLongLines returns false when localStorage is undefined (SSR)", () => {
  (global.window as any) = undefined as any;
  assert.equal(
    readStoredCodeBlockWrapLongLines(),
    false,
    "Should return default false when window is undefined",
  );
});

test("settings-context: sources code-block switches from the app-shell single source", () => {
  const source = readSettingsContextSource();

  // SettingsContext must not keep its own copy of the switch state — that was
  // the triple-state that could drift from AppShellContext / RichCodeBlock.
  assert.doesNotMatch(
    source,
    /const \[codeBlockShowLineNumbers, setCodeBlockShowLineNumbers\] = useState/,
    "SettingsContext must not hold local code-block switch state; read it from useAppShell().",
  );
  assert.doesNotMatch(
    source,
    /const \[codeBlockWrapLongLines, setCodeBlockWrapLongLines\] = useState/,
    "SettingsContext must not hold local code-block switch state; read it from useAppShell().",
  );

  // It reads the values (and delegates writes to) the app-shell context.
  assert.match(
    source,
    /codeBlockShowLineNumbers,[\s\S]*codeBlockWrapLongLines,[\s\S]*=\s*useAppShell\(\)/,
    "SettingsContext should destructure the code-block switch values from useAppShell().",
  );
});
