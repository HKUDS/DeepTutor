import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeLanguage,
  resolveResponseLanguage,
} from "../context/app-shell-storage";

test("response language remains independent from the interface language", () => {
  assert.equal(resolveResponseLanguage("zh", "en"), "zh");
  assert.equal(resolveResponseLanguage("en", "zh"), "en");
});

test("legacy settings inherit the interface language when response language is missing", () => {
  assert.equal(resolveResponseLanguage(null, "zh"), "zh");
  assert.equal(resolveResponseLanguage(undefined, "en"), "en");
});

test("response language accepts French", () => {
  assert.equal(resolveResponseLanguage("fr", "en"), "fr");
  assert.equal(resolveResponseLanguage("fr", "zh"), "fr");
});

test("unknown response languages fall back to the interface language", () => {
  assert.equal(resolveResponseLanguage("de", "zh"), "zh");
  assert.equal(resolveResponseLanguage("nonsense", "en"), "en");
});

test("interface language accepts French and rejects unknown codes", () => {
  assert.equal(normalizeLanguage("fr"), "fr");
  assert.equal(normalizeLanguage("zh"), "zh");
  assert.equal(normalizeLanguage("de"), "en");
  assert.equal(normalizeLanguage(null), "en");
});
