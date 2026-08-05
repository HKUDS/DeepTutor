import test from "node:test";
import assert from "node:assert/strict";

import {
  LANGUAGE_STORAGE_KEY,
  hasStoredLanguage,
  readStoredLanguage,
} from "../context/app-shell-storage";

/** Minimal localStorage stand-in — the helpers only need get/set. */
function withLocalStorage(entries: Record<string, string>, run: () => void) {
  const store = new Map(Object.entries(entries));
  const original = (globalThis as { window?: unknown }).window;
  (globalThis as { window?: unknown }).window = {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    },
    dispatchEvent: () => true,
  };
  try {
    run();
  } finally {
    (globalThis as { window?: unknown }).window = original;
  }
}

test("an absent choice is distinguishable from an explicit English one", () => {
  // readStoredLanguage normalizes both to "en", so the bootstrap cannot use it
  // to decide whether the server-side preference may be adopted.
  withLocalStorage({}, () => {
    assert.equal(hasStoredLanguage(), false);
    assert.equal(readStoredLanguage(), "en");
  });

  withLocalStorage({ [LANGUAGE_STORAGE_KEY]: "en" }, () => {
    assert.equal(hasStoredLanguage(), true);
    assert.equal(readStoredLanguage(), "en");
  });
});

test("a stored choice is reported for either language", () => {
  withLocalStorage({ [LANGUAGE_STORAGE_KEY]: "zh" }, () => {
    assert.equal(hasStoredLanguage(), true);
    assert.equal(readStoredLanguage(), "zh");
  });
});

test("an unusable value still counts as a choice and normalizes to English", () => {
  withLocalStorage({ [LANGUAGE_STORAGE_KEY]: "fr" }, () => {
    assert.equal(hasStoredLanguage(), true);
    assert.equal(readStoredLanguage(), "en");
  });
});

test("server-side rendering reports no stored choice instead of throwing", () => {
  const original = (globalThis as { window?: unknown }).window;
  (globalThis as { window?: unknown }).window = undefined;
  try {
    assert.equal(hasStoredLanguage(), false);
    assert.equal(readStoredLanguage(), "en");
  } finally {
    (globalThis as { window?: unknown }).window = original;
  }
});
