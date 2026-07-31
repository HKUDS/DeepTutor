import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const settingsHubPath = path.join(
  process.cwd(),
  "components",
  "settings",
  "SettingsHub.tsx",
);
const themeSwitcherPath = path.join(
  process.cwd(),
  "components",
  "settings",
  "ThemeSwitcher.tsx",
);

test("settings hub: exposes accessible light and dark theme choices", () => {
  const source = fs.readFileSync(themeSwitcherPath, "utf8");

  assert.match(source, /zh: "浅色", en: "Light"/);
  assert.match(source, /zh: "深色", en: "Dark"/);
  assert.match(source, /role="group"/);
  assert.match(source, /aria-pressed=\{selected\}/);
});

test("settings hub: uses the existing theme state and persistence action", () => {
  const source = fs.readFileSync(settingsHubPath, "utf8");

  assert.match(source, /theme,/);
  assert.match(source, /updateTheme,/);
  assert.match(source, /void updateTheme\(next\)/);
  assert.match(source, /<ThemeSwitcher/);
});

test("settings hub: theme and language controls can wrap on narrow layouts", () => {
  const source = fs.readFileSync(settingsHubPath, "utf8");

  assert.match(source, /w-full shrink-0 flex-wrap items-center justify-between/);
});
