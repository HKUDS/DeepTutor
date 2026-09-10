import test from "node:test";
import assert from "node:assert/strict";

import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
  hasStoredLanguage,
  hasStoredResponseLanguage,
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

test("a browser with only the interface key can still adopt the response language", () => {
  // The two keys were split after the interface language shipped. Gating the
  // bootstrap on hasStoredLanguage alone meant a browser from before the split
  // returned early forever and never picked up the account's model output
  // language — one of the ways "I set Chinese" and "it answers in English"
  // stayed true at the same time.
  withLocalStorage({ [LANGUAGE_STORAGE_KEY]: "zh" }, () => {
    assert.equal(hasStoredLanguage(), true);
    assert.equal(hasStoredResponseLanguage(), false);
  });
  withLocalStorage(
    {
      [LANGUAGE_STORAGE_KEY]: "zh",
      [RESPONSE_LANGUAGE_STORAGE_KEY]: "en",
    },
    () => {
      assert.equal(hasStoredResponseLanguage(), true);
    },
  );
});
