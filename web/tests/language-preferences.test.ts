import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { resolveResponseLanguage } from "../context/app-shell-storage";
import { APP_LANGUAGES, isAppLanguage, normalizeLanguage } from "../i18n/languages";
import { formatDate, formatTime, getLocale } from "../lib/datetime";

test("the locale registry accepts every supported language", () => {
  for (const { code } of APP_LANGUAGES) assert.equal(isAppLanguage(code), true);
  assert.equal(isAppLanguage("xx"), false);
  assert.equal(normalizeLanguage("uk-UA"), "uk");
  assert.equal(normalizeLanguage("fr-FR"), "fr");
  assert.equal(normalizeLanguage("de-AT"), "de");
  assert.equal(normalizeLanguage("pl-PL"), "pl");
  assert.equal(normalizeLanguage("Polish"), "pl");
  assert.equal(normalizeLanguage("Polski"), "pl");
  assert.equal(normalizeLanguage("pt-BR"), "pt");
  assert.equal(normalizeLanguage("pt_PT"), "pt");
  assert.equal(normalizeLanguage("Português"), "pt");
  assert.equal(normalizeLanguage("vi-VN"), "vi");
  assert.equal(normalizeLanguage("vi_VN"), "vi");
  assert.equal(normalizeLanguage("Vietnamese"), "vi");
  assert.equal(normalizeLanguage("Tiếng Việt"), "vi");
  assert.equal(getLocale("vi"), "vi-VN");
  assert.equal(normalizeLanguage("ja-JP"), "ja");
  assert.equal(normalizeLanguage("Japanese"), "ja");
  for (const raw of ["tr", "tr-TR", "tr_TR", "Turkish", "Türkçe"]) {
    assert.equal(normalizeLanguage(raw), "tr");
    assert.equal(resolveResponseLanguage(raw, "en"), "tr");
  }
  assert.equal(getLocale("tr"), "tr-TR");
});

test("response language remains independent from the interface language", () => {
  assert.equal(resolveResponseLanguage("zh", "en"), "zh");
  assert.equal(resolveResponseLanguage("en", "zh"), "en");
  assert.equal(resolveResponseLanguage("fr", "en"), "fr");
  assert.equal(resolveResponseLanguage("en", "fr"), "en");
  assert.equal(resolveResponseLanguage("uk", "en"), "uk");
  assert.equal(resolveResponseLanguage("en", "uk"), "en");
  assert.equal(resolveResponseLanguage("vi", "en"), "vi");
  assert.equal(resolveResponseLanguage("en", "vi"), "en");
  assert.equal(resolveResponseLanguage("vi-VN", "en"), "vi");
  assert.equal(resolveResponseLanguage("Vietnamese", "en"), "vi");
  assert.equal(resolveResponseLanguage("Tiếng Việt", "en"), "vi");
  assert.equal(resolveResponseLanguage("ja", "vi"), "ja");
});

test("response language accepts and normalizes the extended registry", () => {
  assert.equal(resolveResponseLanguage("ja", "en"), "ja");
  assert.equal(resolveResponseLanguage("zh-tw", "en"), "zh-tw");
  assert.equal(resolveResponseLanguage("Japanese", "en"), "ja");
  assert.equal(resolveResponseLanguage("zh-cn", "en"), "zh");
  assert.equal(resolveResponseLanguage("pt-BR", "en"), "pt");
  assert.equal(resolveResponseLanguage("pt_PT", "en"), "pt");
  assert.equal(resolveResponseLanguage("vi_VN", "en"), "vi");
  assert.equal(resolveResponseLanguage("Português", "en"), "pt");
  assert.equal(resolveResponseLanguage("ms-MY", "en"), "ms");
  assert.equal(resolveResponseLanguage("Malay", "en"), "ms");
  assert.equal(resolveResponseLanguage("klingon", "zh"), "zh");
});

test("legacy settings inherit the interface language when response language is missing", () => {
  assert.equal(resolveResponseLanguage(null, "zh"), "zh");
  assert.equal(resolveResponseLanguage(undefined, "en"), "en");
  assert.equal(resolveResponseLanguage(null, "fr"), "fr");
  assert.equal(resolveResponseLanguage(null, "uk"), "uk");
  assert.equal(resolveResponseLanguage(null, "vi"), "vi");
});


test("Portuguese dates and times use Brazilian conventions", () => {
  const date = new Date("2026-03-05T14:05:00Z");
  assert.equal(getLocale("pt"), "pt-BR");
  assert.equal(formatDate(date, "pt", {
    year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
  }), "5 de março de 2026");
  assert.equal(formatTime(date, "pt", {
    hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }), "14:05");
});
