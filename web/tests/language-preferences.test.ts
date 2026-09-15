import test from "node:test";
import assert from "node:assert/strict";

import { resolveResponseLanguage } from "../context/app-shell-storage";

test("response language remains independent from the interface language", () => {
  assert.equal(resolveResponseLanguage("zh", "en"), "zh");
  assert.equal(resolveResponseLanguage("en", "zh"), "en");
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
});
