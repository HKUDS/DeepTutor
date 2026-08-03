import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { CODE_BLOCK_THEME_OPTIONS } from "../components/common/code-block-themes";

const appearancePagePath = path.join(
  process.cwd(),
  "app",
  "(utility)",
  "settings",
  "appearance",
  "page.tsx",
);

function readAppearancePage() {
  return fs.readFileSync(appearancePagePath, "utf8");
}

test("appearance settings page: adds the code blocks section after the theme section", () => {
  const source = readAppearancePage();

  const themeIndex = source.indexOf('title={t("Theme")}');
  const codeBlocksIndex = source.indexOf('title={t("Code blocks")}');

  assert.notEqual(themeIndex, -1, "Theme section should exist");
  assert.notEqual(codeBlocksIndex, -1, "Code blocks section should exist");
  assert.ok(
    codeBlocksIndex > themeIndex,
    "Code blocks section should come after Theme",
  );
});

test("appearance settings page: wires syntax theme select and toggle controls to settings context", () => {
  const source = readAppearancePage();

  assert.match(source, /codeBlockTheme/);
  assert.match(source, /updateCodeBlockTheme/);
  assert.match(source, /codeBlockShowLineNumbers/);
  assert.match(source, /updateCodeBlockShowLineNumbers/);
  assert.match(source, /codeBlockWrapLongLines/);
  assert.match(source, /updateCodeBlockWrapLongLines/);
  assert.match(source, /CODE_BLOCK_THEME_OPTIONS/);
  assert.match(source, /<Toggle/);
});

test("appearance settings page: renders code-block switch checked state from the settings context", () => {
  const source = readAppearancePage();

  // Values come straight from the settings context (backed by AppShellContext,
  // the single source of truth), not a page-local storage-hydrated mirror.
  assert.match(
    source,
    /checked=\{codeBlockShowLineNumbers\}/,
    "Show line numbers switch should render from the context value, not page-local state.",
  );
  assert.match(
    source,
    /checked=\{codeBlockWrapLongLines\}/,
    "Wrap long lines switch should render from the context value, not page-local state.",
  );
  assert.doesNotMatch(
    source,
    /useState\(false\)/,
    "The page must not keep local mirror state for the code-block switches.",
  );
});

test("appearance settings page: exposes every registered code block theme option in the select", () => {
  const source = readAppearancePage();

  assert.ok(CODE_BLOCK_THEME_OPTIONS.length > 0);
  assert.match(source, /CODE_BLOCK_THEME_OPTIONS\.map/);
});

test("appearance settings page: preview includes a line long enough to demonstrate wrapping", () => {
  const source = readAppearancePage();
  const previewSource =
    source.match(/const CODE_BLOCK_PREVIEW_SNIPPET = `([\s\S]*?)`;/)?.[1] ?? "";

  assert.ok(previewSource, "The fixed Python preview snippet should exist");
  assert.ok(
    previewSource.split("\n").some((line) => line.length >= 120),
    "The preview needs a 120+ character line so Wrap long lines has a visible effect",
  );
});
