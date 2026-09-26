import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { accountRoleLabelKey } from "../lib/account-role";

test("all account roles retain distinct display labels", () => {
  assert.equal(accountRoleLabelKey("admin"), "Admin");
  assert.equal(accountRoleLabelKey("teacher"), "Teacher");
  assert.equal(accountRoleLabelKey("student"), "Student");
  assert.equal(accountRoleLabelKey("user"), "User");

  for (const language of ["en", "zh", "de", "fr", "uk"]) {
    const labels = JSON.parse(
      readFileSync(path.resolve(process.cwd(), `locales/${language}/app.json`), "utf8"),
    ) as Record<string, string>;
    for (const role of ["Teacher", "Student"]) {
      assert.ok(labels[role], `${language} is missing ${role}`);
      assert.notEqual(labels[role], labels.User, `${language} displays ${role} as User`);
    }
  }
});
