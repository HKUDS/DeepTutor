import test from "node:test";
import assert from "node:assert/strict";

import { resolveResponseLanguage } from "../context/app-shell-storage";
import {
  isResponseLanguageCode,
  tryParseResponseLanguage,
} from "../lib/response-languages";

test("response language remains independent from the interface language", () => {
  assert.equal(resolveResponseLanguage("zh", "en"), "zh");
  assert.equal(resolveResponseLanguage("en", "zh"), "en");
  assert.equal(resolveResponseLanguage("ja", "en"), "ja");
  assert.equal(resolveResponseLanguage("pl", "zh"), "pl");
});

test("legacy settings inherit the interface language when response language is missing", () => {
  assert.equal(resolveResponseLanguage(null, "zh"), "zh");
  assert.equal(resolveResponseLanguage(undefined, "en"), "en");
});

test("unusable response language codes fall back instead of collapsing to Chinese", () => {
  assert.equal(resolveResponseLanguage("klingon", "en"), "en");
  assert.equal(resolveResponseLanguage("not a language", "ja"), "ja");
  assert.equal(tryParseResponseLanguage("sk-arbitrary-key"), null);
  assert.equal(isResponseLanguageCode("pl"), true);
  assert.equal(isResponseLanguageCode("zh-tw"), true);
});
