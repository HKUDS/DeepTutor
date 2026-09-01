import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

const api = readWebFile("lib", "guardian-api.ts");
const page = readWebFile(
  "app",
  "(utility)",
  "settings",
  "guardian",
  "page.tsx",
);
const adminEditor = readWebFile(
  "features",
  "multi-user",
  "components",
  "GuardianRelationshipsEditor.tsx",
);

test("guardian credential reset never returns or renders a plaintext credential", () => {
  assert.match(api, /JSON\.stringify\(\{ new_password: newPassword \}\)/);
  assert.doesNotMatch(api, /temporary_password/);
  assert.doesNotMatch(page, /Temporary password|setTemporaryPassword|clipboard/);
  assert.doesNotMatch(adminEditor, /Temporary password|setTemporaryPassword|clipboard/);
  assert.match(page, /type="password"/);
  assert.match(adminEditor, /type="password"/);
});

test("guardian actions follow each relationship permission", () => {
  assert.match(page, /can\("view_reports"\)/);
  assert.match(page, /can\("assign_materials"\)/);
  assert.match(page, /can\("manage_restrictions"\)/);
  assert.match(page, /can\("reset_credentials"\)/);
  assert.match(page, /revokeMyGuardianRelationship/);
  assert.match(page, /saveGuardianMaterials/);
  assert.match(page, /saveGuardianRestrictions/);
  assert.match(page, /<ConfirmDialog/);
});

test("administrators can create, review, revoke, and reset guardian access", () => {
  assert.match(adminEditor, /listAdminGuardianRelationships/);
  assert.match(adminEditor, /authorizeGuardianRelationship/);
  assert.match(adminEditor, /revokeGuardianRelationship/);
  assert.match(adminEditor, /getGuardianReport/);
  assert.match(adminEditor, /resetLearnerCredentials/);
  assert.match(adminEditor, /PERMISSIONS/);
});

test("settings visibility uses the account preset rather than policy presence", () => {
  const nav = readWebFile("components", "settings", "SettingsNav.tsx");
  assert.match(nav, /showLearnerOnly: authStatus\.preset === "learner"/);
  assert.match(nav, /authStatus\.preset === "standard"/);
  assert.match(nav, /authStatus\.preset === "custom"/);
});

test("guardian management copy is localized", () => {
  const en = JSON.parse(readWebFile("locales", "en", "app.json")) as Record<
    string,
    string
  >;
  const zh = JSON.parse(readWebFile("locales", "zh", "app.json")) as Record<
    string,
    string
  >;
  for (const key of [
    "Guardian management",
    "Approved materials",
    "Manage restrictions",
    "Revoke guardian access",
    "Save materials",
    "Learning restrictions",
    "Guardian relationships",
    "Reset learner credentials",
    "This changes the learner password and revokes every learner device credential.",
  ]) {
    assert.ok(en[key], `missing English key: ${key}`);
    assert.ok(zh[key], `missing Chinese key: ${key}`);
  }
});
