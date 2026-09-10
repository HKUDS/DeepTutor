import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { CODE_BLOCK_THEME_OPTIONS } from "../components/common/code-block-themes";

const appearancePagePath = path.join(
  process.cwd(),
  "features",
  "settings",
  "sections",
  "AppearanceSettingsSection.tsx",
);

const overviewPagePath = path.join(
  process.cwd(),
  "components",
  "settings",
  "SettingsOverview.tsx",
);

function readAppearancePage() {
  return fs.readFileSync(appearancePagePath, "utf8");
}

function readOverviewPage() {
  return fs.readFileSync(overviewPagePath, "utf8");
}

test("settings source contract: language settings live on Overview instead of Appearance", () => {
  const appearance = readAppearancePage();
  const overview = readOverviewPage();

  assert.doesNotMatch(appearance, /title=\{t\("Language"\)\}/);
  assert.doesNotMatch(appearance, /updateLanguage|updateResponseLanguage/);
  assert.match(overview, /title=\{t\("Language"\)\}/);
  assert.match(overview, /updateLanguage/);
  assert.match(overview, /updateResponseLanguage/);
});

test("appearance source contract: code blocks section follows the theme section", () => {
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

test("appearance source contract: code-block controls use the settings context", () => {
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

test("appearance source contract: switch checked state has no page-local mirror", () => {
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

test("appearance source contract: select maps the shared theme registry", () => {
  const source = readAppearancePage();

  assert.ok(CODE_BLOCK_THEME_OPTIONS.length > 0);
  assert.match(source, /CODE_BLOCK_THEME_OPTIONS\.map/);
});

test("appearance source contract: preview contains a line that demonstrates wrapping", () => {
  const source = readAppearancePage();
  const previewSource =
    source.match(/const CODE_BLOCK_PREVIEW_SNIPPET = `([\s\S]*?)`;/)?.[1] ?? "";

  assert.ok(previewSource, "The fixed Python preview snippet should exist");
  assert.ok(
    previewSource.split("\n").some((line) => line.length >= 120),
    "The preview needs a 120+ character line so Wrap long lines has a visible effect",
  );
});
