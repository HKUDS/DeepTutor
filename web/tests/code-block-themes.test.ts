import { test } from "node:test";
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  CODE_BLOCK_THEME_OPTIONS,
  DEFAULT_CODE_BLOCK_THEME_ID,
  getCodeBlockTheme,
  getCodeBlockThemeBackground,
} from "../components/common/code-block-themes";

test("code-block-themes: registry has exactly 46 options", () => {
  assert.equal(CODE_BLOCK_THEME_OPTIONS.length, 46);
});

test("code-block-themes: every option has a non-null style object", () => {
  for (const option of CODE_BLOCK_THEME_OPTIONS) {
    assert.ok(option.style, `Theme ${option.id} has a null style object`);
    assert.ok(
      typeof option.style === "object",
      `Theme ${option.id} style is not an object`,
    );
  }
});

test("code-block-themes: default theme ID is oneDark", () => {
  assert.equal(DEFAULT_CODE_BLOCK_THEME_ID, "oneDark");
});

test("code-block-themes: every option ID is unique", () => {
  const ids = CODE_BLOCK_THEME_OPTIONS.map((opt) => opt.id);
  const uniqueIds = new Set(ids);
  assert.equal(uniqueIds.size, ids.length, "All theme IDs should be unique");
});

test("code-block-themes: every option has a non-empty label", () => {
  for (const option of CODE_BLOCK_THEME_OPTIONS) {
    assert.ok(
      option.label && option.label.trim().length > 0,
      `Theme ${option.id} has an empty label`,
    );
  }
});

test("code-block-themes: getCodeBlockTheme returns the correct style for valid IDs", () => {
  const oneDarkOption = CODE_BLOCK_THEME_OPTIONS.find(
    (opt) => opt.id === "oneDark",
  );
  assert.ok(oneDarkOption, "oneDark option should exist");

  const style = getCodeBlockTheme("oneDark");
  assert.strictEqual(style, oneDarkOption?.style);

  // Test a few more themes
  const draculaStyle = getCodeBlockTheme("dracula");
  assert.ok(draculaStyle, "dracula style should be non-null");

  const vscDarkPlusStyle = getCodeBlockTheme("vscDarkPlus");
  assert.ok(vscDarkPlusStyle, "vscDarkPlus style should be non-null");
});

test("code-block-themes: getCodeBlockTheme falls back to oneDark for invalid IDs", () => {
  const oneDarkStyle = CODE_BLOCK_THEME_OPTIONS.find(
    (opt) => opt.id === "oneDark",
  )?.style;
  assert.ok(oneDarkStyle, "oneDark style should exist");

  const invalidStyle = getCodeBlockTheme("non-existent-theme");
  assert.strictEqual(invalidStyle, oneDarkStyle);

  const emptyStyle = getCodeBlockTheme("");
  assert.strictEqual(emptyStyle, oneDarkStyle);

  const undefinedStyle = getCodeBlockTheme(undefined as any);
  assert.strictEqual(undefinedStyle, oneDarkStyle);
});

test("code-block-themes: getCodeBlockThemeBackground extracts background color", () => {
  const oneDarkOption = CODE_BLOCK_THEME_OPTIONS.find(
    (opt) => opt.id === "oneDark",
  );
  assert.ok(oneDarkOption, "oneDark option should exist");

  const background = getCodeBlockThemeBackground(oneDarkOption.style);
  // oneDark should have a background color
  assert.ok(background, "oneDark theme should have a background color");
  assert.ok(typeof background === "string", "background should be a string");
});

test("code-block-themes: getCodeBlockThemeBackground returns undefined when no background", () => {
  const minimalStyle = {} as any;
  const background = getCodeBlockThemeBackground(minimalStyle);
  assert.strictEqual(background, undefined);
});

test("code-block-themes: getCodeBlockThemeBackground handles backgroundColor-only themes", () => {
  const backgroundColorOnlyStyle = {
    'pre[class*="language-"]': {
      backgroundColor: "#fdf6e3",
    },
  } as any;

  const background = getCodeBlockThemeBackground(backgroundColorOnlyStyle);
  assert.strictEqual(
    background,
    "#fdf6e3",
    "backgroundColor-only themes should return their backgroundColor",
  );
});

test("code-block-themes: getCodeBlockThemeBackground prefers backgroundColor over background", () => {
  const bothPropertiesStyle = {
    'pre[class*="language-"]': {
      backgroundColor: "#fdf6e3",
      background: "#1f2937",
    },
  } as any;

  const background = getCodeBlockThemeBackground(bothPropertiesStyle);
  assert.strictEqual(
    background,
    "#fdf6e3",
    "backgroundColor should take precedence over background",
  );
});

test("code-block-themes: all 46 theme IDs are from the installed Prism files", () => {
  const expectedIds = [
    "a11yDark",
    "a11yOneLight",
    "atomDark",
    "base16AteliersulphurpoolLight",
    "cb",
    "coldarkCold",
    "coldarkDark",
    "coyWithoutShadows",
    "coy",
    "darcula",
    "dark",
    "dracula",
    "duotoneDark",
    "duotoneEarth",
    "duotoneForest",
    "duotoneLight",
    "duotoneSea",
    "duotoneSpace",
    "funky",
    "ghcolors",
    "gruvboxDark",
    "gruvboxLight",
    "holiTheme",
    "hopscotch",
    "lucario",
    "materialDark",
    "materialLight",
    "materialOceanic",
    "nightOwl",
    "nord",
    "okaidia",
    "oneDark",
    "oneLight",
    "pojoaque",
    "prism",
    "shadesOfPurple",
    "solarizedDarkAtom",
    "solarizedlight",
    "synthwave84",
    "tomorrow",
    "twilight",
    "vsDark",
    "vs",
    "vscDarkPlus",
    "xonokai",
    "zTouch",
  ];

  const actualIds = CODE_BLOCK_THEME_OPTIONS.map((opt) => opt.id).sort();
  assert.deepStrictEqual(
    actualIds,
    expectedIds.sort(),
    "Theme IDs should match expected list",
  );
});

test("code-block-themes: every theme in expected list has a style", () => {
  for (const id of CODE_BLOCK_THEME_OPTIONS.map((opt) => opt.id)) {
    const style = getCodeBlockTheme(id);
    assert.ok(style, `Theme ${id} should resolve to a style object`);
  }
});

test("app-shell-context: theme change subscription is registered exactly once", () => {
  const source = readFileSync(
    path.join(process.cwd(), "context", "AppShellContext.tsx"),
    "utf8",
  );
  const matches = source.match(/subscribeToThemeChanges\s*\(/g) ?? [];
  assert.equal(matches.length, 1);
});
