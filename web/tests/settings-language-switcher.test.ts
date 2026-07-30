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
const languageSwitcherPath = path.join(
  process.cwd(),
  "components",
  "settings",
  "LanguageSwitcher.tsx",
);

function readSettingsHub() {
  return fs.readFileSync(settingsHubPath, "utf8");
}

function readLanguageSwitcher() {
  return fs.readFileSync(languageSwitcherPath, "utf8");
}

test("settings hub: exposes English and Simplified Chinese language choices", () => {
  const source = readLanguageSwitcher();

  assert.match(source, /label: "English"/);
  assert.match(source, /label: "简体中文"/);
  assert.match(source, /role="group"/);
  assert.match(source, /aria-label=\{tr\(\{ zh: "界面语言", en: "Interface language" \}\)\}/);
});

test("settings hub: uses the existing global language state and persistence action", () => {
  const hubSource = readSettingsHub();
  const switcherSource = readLanguageSwitcher();

  assert.match(hubSource, /language,/);
  assert.match(hubSource, /updateLanguage,/);
  assert.match(hubSource, /void updateLanguage\(next\)/);
  assert.match(switcherSource, /aria-pressed=\{selected\}/);
  assert.doesNotMatch(
    hubSource,
    /useState<["']en["'] \| ["']zh["']>/,
    "The settings hub must not create a second language state.",
  );
});

test("settings hub: keeps language controls usable on narrow layouts", () => {
  const hubSource = readSettingsHub();
  const switcherSource = readLanguageSwitcher();

  assert.match(
    hubSource,
    /flex-col items-start justify-between gap-4 sm:flex-row/,
  );
  assert.match(hubSource, /w-full shrink-0 items-center justify-between/);
  assert.match(switcherSource, /type="button"/);
});
