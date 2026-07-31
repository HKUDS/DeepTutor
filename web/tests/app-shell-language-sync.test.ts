import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { fetchBackendUiPreferences } from "../context/app-shell-ui-settings";

const appShellContextPath = path.join(
  process.cwd(),
  "context",
  "AppShellContext.tsx",
);

test("app shell: reads the saved backend language for a new browser", async () => {
  let capturedInput: RequestInfo | URL | undefined;
  let capturedInit:
    | (RequestInit & { skipAuthRedirect?: boolean })
    | undefined;

  const preferences = await fetchBackendUiPreferences(async (input, init) => {
    capturedInput = input;
    capturedInit = init;
    return {
      ok: true,
      json: async () => ({ ui: { language: "zh", theme: "dark" } }),
    } as Response;
  });

  assert.deepEqual(preferences, { language: "zh", theme: "dark" });
  assert.match(String(capturedInput), /\/api\/v1\/settings$/);
  assert.equal(capturedInit?.skipAuthRedirect, true);
});

test("app shell: ignores unavailable or malformed backend language", async () => {
  const unavailable = await fetchBackendUiPreferences(
    async () => ({ ok: false }) as Response,
  );
  const malformed = await fetchBackendUiPreferences(
    async () =>
      ({
        ok: true,
        json: async () => ({
          ui: { language: "unexpected", theme: "neon" },
        }),
      }) as Response,
  );

  assert.equal(unavailable, null);
  assert.equal(malformed, null);
});

test("app shell: backend language sync updates the global language source", () => {
  const source = fs.readFileSync(appShellContextPath, "utf8");

  assert.match(source, /fetchBackendUiPreferences\(\)/);
  assert.match(source, /writeStoredLanguage\(preferences\.language\)/);
  assert.match(source, /setLanguageState\(preferences\.language\)/);
  assert.match(source, /applyThemePreference\(preferences\.theme\)/);
  assert.match(source, /setThemeState\(preferences\.theme\)/);
  assert.match(
    source,
    /languageRevisionAtStart === languageRevisionRef\.current/,
    "A late backend response must not overwrite a newer user selection.",
  );
  assert.match(source, /themeRevisionAtStart === themeRevisionRef\.current/);
});
