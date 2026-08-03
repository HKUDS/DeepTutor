import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import RichCodeBlock from "../components/common/RichCodeBlock";
import { AppShellProvider } from "../context/AppShellContext";
import {
  getCodeBlockTheme,
  getCodeBlockThemeBackground,
} from "../components/common/code-block-themes";
import {
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  CODE_BLOCK_THEME_STORAGE_KEY,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
} from "../context/app-shell-storage";

let mockLocalStorage: Record<string, string> = {};
let mockSessionStorage: Record<string, string> = {};

function installMockWindow() {
  const localStorage = {
    getItem: (key: string) => mockLocalStorage[key] ?? null,
    setItem: (key: string, value: string) => {
      mockLocalStorage[key] = value;
    },
    removeItem: (key: string) => {
      delete mockLocalStorage[key];
    },
  };

  const sessionStorage = {
    getItem: (key: string) => mockSessionStorage[key] ?? null,
    setItem: (key: string, value: string) => {
      mockSessionStorage[key] = value;
    },
    removeItem: (key: string) => {
      delete mockSessionStorage[key];
    },
  };

  global.window = {
    localStorage,
    sessionStorage,
    dispatchEvent: () => true,
    addEventListener: () => {},
    removeEventListener: () => {},
    matchMedia: () => ({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => true,
    }),
  } as any;

  global.localStorage = localStorage as any;
  global.sessionStorage = sessionStorage as any;
}

installMockWindow();

function renderCodeBlock(raw: string, lang: string) {
  return renderToStaticMarkup(
    React.createElement(
      AppShellProvider,
      null,
      React.createElement(RichCodeBlock, { raw, lang }),
    ),
  );
}

test("rich-code-block: highlighted blocks use selected theme background instead of hardcoded dark styling", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "oneLight",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "false",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "false",
  };
  mockSessionStorage = {};

  const html = renderCodeBlock("const value = 1;", "js");
  const oneLightBackground = getCodeBlockThemeBackground(
    getCodeBlockTheme("oneLight"),
  );

  assert.ok(oneLightBackground, "oneLight should expose a background color");
  assert.match(
    html,
    new RegExp(
      `background(?:-color)?:${oneLightBackground.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
    ),
  );
  assert.doesNotMatch(html, /background:#1f2937/);
});

test("rich-code-block: highlighted blocks honor line-number and wrap preferences", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "dracula",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "true",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "true",
  };
  mockSessionStorage = {};

  const html = renderCodeBlock("print('hello')\nprint('world')", "python");

  assert.match(html, /react-syntax-highlighter-line-number/);
  // The outer <pre> must itself wrap; matching pre-wrap only on the inner
  // <code> gave false confidence while long lines were clipped at runtime.
  assert.match(html, /<pre[^>]*style="[^"]*white-space:pre-wrap[^"]*"/);
});

test("rich-code-block: plain text blocks honor line-number and wrap preferences", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "oneDark",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "true",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "true",
  };
  mockSessionStorage = {};

  const html = renderCodeBlock("plain text line\nanother line", "text");

  assert.match(html, /react-syntax-highlighter-line-number/);
  assert.match(html, /<pre[^>]*style="[^"]*white-space:pre-wrap[^"]*"/);
  assert.doesNotMatch(html, /unknown language/i);
});

test("rich-code-block: wrap disabled keeps the outer <pre> unwrapped and horizontally scrollable", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "dracula",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "false",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "false",
  };
  mockSessionStorage = {};

  const html = renderCodeBlock(
    "const veryLongLine = 'this should stay on one line and scroll instead of wrapping';",
    "javascript",
  );

  // When wrap is off, the outer <pre> must NOT receive pre-wrap (otherwise
  // wrapping would be forced even with the setting disabled) and must keep
  // horizontal scroll available so long lines are reachable, not clipped.
  assert.doesNotMatch(html, /<pre[^>]*style="[^"]*white-space:pre-wrap[^"]*"/);
  assert.match(html, /<pre[^>]*style="[^"]*overflow-x:auto[^"]*"/);
});

test("rich-code-block: wrap mode breaks long unbroken tokens instead of clipping them", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "oneLight",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "false",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "true",
  };
  mockSessionStorage = {};

  // F3 browser-proven case: a 200-char unbroken token (no whitespace) still
  // overflowed with only white-space:pre-wrap on the outer <pre>, because
  // pre-wrap breaks only at whitespace and a long identifier/string/URL has
  // no break opportunity. The renderer must additionally emit
  // word-wrap:break-word so the browser is permitted to split the token
  // mid-word when it would otherwise overflow. Asserting on BOTH the outer
  // <pre> and the inner <code> because the line layout uses per-line flex
  // rows and inheritance must reach the token spans from both levels.
  const longUnbrokenToken = "a".repeat(200);
  const html = renderCodeBlock(longUnbrokenToken, "javascript");

  assert.match(html, /<pre[^>]*style="[^"]*word-wrap:break-word[^"]*"/);
  assert.match(html, /<code[^>]*style="[^"]*word-wrap:break-word[^"]*"/);
});

test("rich-code-block: wrap + line-numbers does not let per-line flex wrappers defeat overflow-wrap", () => {
  mockLocalStorage = {
    [CODE_BLOCK_THEME_STORAGE_KEY]: "oneLight",
    [CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY]: "true",
    [CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY]: "true",
  };
  mockSessionStorage = {};

  // F3 rerun-2 browser-proven case: with wrap AND line-numbers both on,
  // react-syntax-highlighter's highlight.js (lines 99-103) forces each
  // per-line span wrapper to display:flex so the line-number gutter can
  // align in a column. That flex layout makes each token span a flex item
  // with the default min-width:auto, which CANNOT shrink below content
  // size — so a long unbreakable token overflows the line wrapper (F3
  // measured the nested flex line wrapper at clientWidth 536 /
  // scrollWidth 4326 for the short-token case, and 536 / 2319 for the
  // 240-char unbroken-token case). word-wrap:break-word was already
  // correctly set on <pre> and <code> but could not propagate its break
  // behavior into unshrinkable flex items, so the visible result was a
  // horizontal clip. The outer-<pre> and overflow-wrap regressions above
  // guard the previously fixed layers; this regression guards the
  // remaining flex-line-wrapper cause specifically.
  const longUnbrokenToken = "a".repeat(200);
  const html = renderCodeBlock(`${longUnbrokenToken} tail`, "javascript");

  // Line numbers must still be emitted so we know we are exercising the
  // wrap+line-numbers code path that triggers the library's display:flex.
  assert.match(html, /react-syntax-highlighter-line-number/);

  const codeMatch = html.match(/<code[^>]*>([\s\S]*?)<\/code>/);
  assert.ok(codeMatch, "<code> element should exist in rendered output");
  const codeInner = codeMatch[1];

  // No span inside <code> may carry display:flex when wrap is enabled:
  // that style is the proximate cause of the F3 live-browser clip. The
  // per-line wrapper must lay out as a normal block instead so that
  // word-wrap:break-word (inherited from <pre>/<code>) can break
  // long unbreakable tokens instead of being defeated by flex items
  // whose min-width:auto refuses to shrink.
  assert.doesNotMatch(
    codeInner,
    /<span[^>]*style="[^"]*display:\s*flex[^"]*"/,
    "per-line span wrapper inside <code> must not be display:flex when wrap is enabled",
  );
});
