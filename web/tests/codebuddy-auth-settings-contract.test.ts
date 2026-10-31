import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { shouldPollCodeBuddyAuth } from "../lib/codebuddy-auth";

const EN = path.resolve(process.cwd(), "locales/en/app.json");
const ZH = path.resolve(process.cwd(), "locales/zh/app.json");

test("CodeBuddy auth polling only runs while browser authorization is waiting", () => {
  const base = {
    connection: "authorizing" as const,
    operation_state: "waiting" as const,
    authorize_url: "https://codebuddy.example/login",
    user_label: null,
    error_code: null,
  };

  assert.equal(shouldPollCodeBuddyAuth(base), true);
  assert.equal(
    shouldPollCodeBuddyAuth({
      ...base,
      connection: "connected",
      operation_state: "completed",
    }),
    false,
  );
});

test("CodeBuddy auth copy stays in sync across locales", () => {
  const en = JSON.parse(readFileSync(EN, "utf8")) as Record<string, unknown>;
  const zh = JSON.parse(readFileSync(ZH, "utf8")) as Record<string, unknown>;
  const keys = (locale: Record<string, unknown>) =>
    Object.keys(locale)
      .filter((key) => key.startsWith("codebuddy.auth."))
      .sort();

  assert.deepEqual(keys(en), keys(zh));
  for (const key of keys(en)) {
    assert.equal(typeof en[key], "string");
    assert.equal(typeof zh[key], "string");
  }
});
