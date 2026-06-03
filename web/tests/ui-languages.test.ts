import test from "node:test";
import assert from "node:assert/strict";

import {
  SUPPORTED_UI_LANGUAGES,
  isSupportedUiLanguage,
  normalizeUiLanguage,
  uiLanguageOptions,
  type AppLanguage,
} from "../lib/ui-languages";
import {
  normalizeLanguage as normalizeStoredLanguage,
  type AppLanguage as StoredAppLanguage,
} from "../context/app-shell-storage";

test("SUPPORTED_UI_LANGUAGES exposes English, Chinese, and German in dropdown order", () => {
  assert.deepEqual(SUPPORTED_UI_LANGUAGES, ["en", "zh", "de"]);
  assert.deepEqual(
    uiLanguageOptions.map((option) => option.value),
    ["en", "zh", "de"],
  );
});

test("language registry labels every supported UI language with translation keys", () => {
  assert.deepEqual(uiLanguageOptions, [
    { value: "en", labelKey: "language.english" },
    { value: "zh", labelKey: "language.chinese" },
    { value: "de", labelKey: "language.german" },
  ]);
});

test("isSupportedUiLanguage accepts only complete UI locales", () => {
  assert.equal(isSupportedUiLanguage("en"), true);
  assert.equal(isSupportedUiLanguage("zh"), true);
  assert.equal(isSupportedUiLanguage("de"), true);
  assert.equal(isSupportedUiLanguage("fr"), false);
  assert.equal(isSupportedUiLanguage(""), false);
  assert.equal(isSupportedUiLanguage(undefined), false);
});

test("shared language normalization accepts supported aliases", () => {
  const cases: Array<[unknown, AppLanguage]> = [
    ["en", "en"],
    ["english", "en"],
    ["en-US", "en"],
    ["zh", "zh"],
    ["cn", "zh"],
    ["chinese", "zh"],
    ["de", "de"],
    ["de-DE", "de"],
    ["de_de", "de"],
    ["german", "de"],
    ["deutsch", "de"],
    ["fr", "en"],
    [null, "en"],
  ];

  for (const [input, expected] of cases) {
    assert.equal(normalizeUiLanguage(input), expected);
  }
});

test("stored language normalization delegates to shared normalization", () => {
  const cases: Array<[unknown, StoredAppLanguage]> = [
    ["english", "en"],
    ["cn", "zh"],
    ["de_DE", "de"],
    ["unsupported", "en"],
  ];

  for (const [input, expected] of cases) {
    assert.equal(normalizeStoredLanguage(input), expected);
    assert.equal(normalizeStoredLanguage(input), normalizeUiLanguage(input));
  }
});
