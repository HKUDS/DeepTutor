import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { resolveResponseLanguage } from "../context/app-shell-storage";
import { APP_LANGUAGES, isAppLanguage, normalizeLanguage } from "../i18n/languages";

test("the locale registry accepts every supported language", () => {
  assert.deepEqual(APP_LANGUAGES, ["en", "zh", "es", "fr", "uk"]);
  for (const code of APP_LANGUAGES) assert.equal(isAppLanguage(code), true);
  assert.equal(isAppLanguage("de"), false);
  assert.equal(normalizeLanguage("uk-UA"), "uk");
  assert.equal(normalizeLanguage("fr-FR"), "fr");
});

test("response language remains independent from the interface language", () => {
  assert.equal(resolveResponseLanguage("zh", "en"), "zh");
  assert.equal(resolveResponseLanguage("en", "zh"), "en");
  assert.equal(resolveResponseLanguage("es", "zh"), "es");
  assert.equal(resolveResponseLanguage("fr", "en"), "fr");
  assert.equal(resolveResponseLanguage("en", "fr"), "en");
  assert.equal(resolveResponseLanguage("uk", "en"), "uk");
  assert.equal(resolveResponseLanguage("en", "uk"), "en");
});

test("response language accepts and normalizes the extended registry", () => {
  assert.equal(resolveResponseLanguage("ja", "en"), "ja");
  assert.equal(resolveResponseLanguage("zh-tw", "en"), "zh-tw");
  assert.equal(resolveResponseLanguage("Japanese", "en"), "ja");
  assert.equal(resolveResponseLanguage("zh-cn", "en"), "zh");
  assert.equal(resolveResponseLanguage("pt-BR", "en"), "pt");
  assert.equal(resolveResponseLanguage("klingon", "zh"), "zh");
});

test("legacy settings inherit the interface language when response language is missing", () => {
  assert.equal(resolveResponseLanguage(null, "zh"), "zh");
  assert.equal(resolveResponseLanguage(undefined, "en"), "en");
  assert.equal(resolveResponseLanguage(undefined, "es"), "es");
  assert.equal(resolveResponseLanguage(null, "fr"), "fr");
  assert.equal(resolveResponseLanguage(null, "uk"), "uk");
});
