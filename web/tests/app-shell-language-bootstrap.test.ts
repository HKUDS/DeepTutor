import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { loadBackendLanguage } from "../context/AppShellContext";

test("app shell loads the persisted language from the lightweight UI endpoint", async () => {
  let capturedInput: RequestInfo | URL | undefined;

  const language = await loadBackendLanguage(async (input) => {
    capturedInput = input;
    return {
      ok: true,
      json: async () => ({ language: "zh" }),
    } as Response;
  });

  assert.equal(capturedInput, "/api/v1/settings/ui");
  assert.equal(language, "zh");
});

test("app shell ignores failed or malformed language bootstrap responses", async () => {
  assert.equal(
    await loadBackendLanguage(
      async () => ({ ok: false, json: async () => ({}) }) as Response,
    ),
    null,
  );
  assert.equal(
    await loadBackendLanguage(
      async () =>
        ({ ok: true, json: async () => ({ language: "fr" }) }) as Response,
    ),
    null,
  );
});

test("app shell reconciles backend language into storage and global state", () => {
  const source = fs.readFileSync(
    path.join(process.cwd(), "context", "AppShellContext.tsx"),
    "utf8",
  );

  assert.match(source, /void loadBackendLanguage\(\)\.then/);
  assert.match(source, /writeStoredLanguage\(backendLanguage\)/);
  assert.match(source, /setLanguageState\(backendLanguage\)/);
});
