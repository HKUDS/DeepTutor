import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { fetchBackendLanguage } from "../context/app-shell-ui-settings";

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

  const language = await fetchBackendLanguage(async (input, init) => {
    capturedInput = input;
    capturedInit = init;
    return {
      ok: true,
      json: async () => ({ ui: { language: "zh" } }),
    } as Response;
  });

  assert.equal(language, "zh");
  assert.match(String(capturedInput), /\/api\/v1\/settings$/);
  assert.equal(capturedInit?.skipAuthRedirect, true);
});

test("app shell: ignores unavailable or malformed backend language", async () => {
  const unavailable = await fetchBackendLanguage(
    async () => ({ ok: false }) as Response,
  );
  const malformed = await fetchBackendLanguage(
    async () =>
      ({
        ok: true,
        json: async () => ({ ui: { language: "unexpected" } }),
      }) as Response,
  );

  assert.equal(unavailable, null);
  assert.equal(malformed, null);
});

test("app shell: backend language sync updates the global language source", () => {
  const source = fs.readFileSync(appShellContextPath, "utf8");

  assert.match(source, /fetchBackendLanguage\(\)/);
  assert.match(source, /writeStoredLanguage\(nextLanguage\)/);
  assert.match(source, /setLanguageState\(nextLanguage\)/);
  assert.match(
    source,
    /revisionAtStart !== languageRevisionRef\.current/,
    "A late backend response must not overwrite a newer user selection.",
  );
});
