import test from "node:test";
import assert from "node:assert/strict";

// Mock window localStorage for node test environment
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
    dispatchEvent: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
  } as any;
}

mockWindow();

// Import after mocking window
import {
  CODE_BLOCK_THEME_STORAGE_KEY,
  DEFAULT_CODE_BLOCK_THEME,
  readStoredCodeBlockTheme,
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS,
  readStoredCodeBlockShowLineNumbers,
  writeStoredCodeBlockTheme,
  writeStoredCodeBlockShowLineNumbers,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
  DEFAULT_CODE_BLOCK_WRAP_LONG_LINES,
  readStoredCodeBlockWrapLongLines,
  writeStoredCodeBlockWrapLongLines,
  CODE_BLOCK_SETTINGS_EVENT,
} from "../context/app-shell-storage";

test("app-shell-storage: code block theme defaults to oneDark", () => {
  assert.equal(DEFAULT_CODE_BLOCK_THEME, "oneDark");
  assert.equal(CODE_BLOCK_THEME_STORAGE_KEY, "deeptutor.code-block-theme");

  // When no value is stored, read returns default
  mockLocalStorage = {}; // Clear
  const theme = readStoredCodeBlockTheme();
  assert.equal(theme, "oneDark");
});

test("app-shell-storage: code block show line numbers defaults to false", () => {
  assert.equal(DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS, false);
  assert.equal(
    CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
    "deeptutor.code-block-show-line-numbers",
  );

  // When no value is stored, read returns default
  mockLocalStorage = {}; // Clear
  const showLineNumbers = readStoredCodeBlockShowLineNumbers();
  assert.equal(showLineNumbers, false);
});

test("app-shell-storage: code block wrap long lines defaults to false", () => {
  assert.equal(DEFAULT_CODE_BLOCK_WRAP_LONG_LINES, false);
  assert.equal(
    CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
    "deeptutor.code-block-wrap-long-lines",
  );

  // When no value is stored, read returns default
  mockLocalStorage = {}; // Clear
  const wrapLongLines = readStoredCodeBlockWrapLongLines();
  assert.equal(wrapLongLines, false);
});

test("app-shell-storage: write and read code block theme", () => {
  // Clear first
  mockLocalStorage = {};

  // Write a theme
  writeStoredCodeBlockTheme("dracula");
  assert.equal(readStoredCodeBlockTheme(), "dracula");

  // Write another theme
  writeStoredCodeBlockTheme("oneLight");
  assert.equal(readStoredCodeBlockTheme(), "oneLight");
});

test("app-shell-storage: write and read code block show line numbers", () => {
  // Clear first
  mockLocalStorage = {};

  // Write true
  writeStoredCodeBlockShowLineNumbers(true);
  assert.equal(readStoredCodeBlockShowLineNumbers(), true);

  // Write false
  writeStoredCodeBlockShowLineNumbers(false);
  assert.equal(readStoredCodeBlockShowLineNumbers(), false);
});

test("app-shell-storage: write and read code block wrap long lines", () => {
  // Clear first
  mockLocalStorage = {};

  // Write true
  writeStoredCodeBlockWrapLongLines(true);
  assert.equal(readStoredCodeBlockWrapLongLines(), true);

  // Write false
  writeStoredCodeBlockWrapLongLines(false);
  assert.equal(readStoredCodeBlockWrapLongLines(), false);
});

test("app-shell-storage: CODE_BLOCK_SETTINGS_EVENT constant exists", () => {
  assert.equal(CODE_BLOCK_SETTINGS_EVENT, "deeptutor:code-block-settings");
});

test("app-shell-storage: write dispatches CODE_BLOCK_SETTINGS_EVENT", () => {
  let dispatchedEvents: Array<{ type: string; detail: any }> = [];

  (global.window as any).dispatchEvent = (event: any) => {
    dispatchedEvents.push({ type: event.type, detail: event.detail });
  };

  // Clear and write
  mockLocalStorage = {};
  dispatchedEvents = [];

  writeStoredCodeBlockTheme("dracula");
  assert.equal(dispatchedEvents.length, 1);
  assert.equal(dispatchedEvents[0].type, CODE_BLOCK_SETTINGS_EVENT);
  assert.equal(dispatchedEvents[0].detail.codeBlockTheme, "dracula");

  // Write another setting
  writeStoredCodeBlockShowLineNumbers(true);
  assert.equal(dispatchedEvents.length, 2);
  assert.equal(dispatchedEvents[1].type, CODE_BLOCK_SETTINGS_EVENT);
  assert.equal(dispatchedEvents[1].detail.codeBlockShowLineNumbers, true);

  writeStoredCodeBlockWrapLongLines(false);
  assert.equal(dispatchedEvents.length, 3);
  assert.equal(dispatchedEvents[2].type, CODE_BLOCK_SETTINGS_EVENT);
  assert.equal(dispatchedEvents[2].detail.codeBlockWrapLongLines, false);
});
