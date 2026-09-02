import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  PENDING_SETTINGS_ACCESS,
  settingsAccessFromAuthStatus,
} from "../features/settings/navigation/settings-access";
import {
  isSettingsCategoryVisible,
  SETTINGS_CATEGORIES,
} from "../features/settings/navigation/settings-nav";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

const api = readWebFile("lib", "guardian-api.ts");
const page = readWebFile(
  "features",
  "settings",
  "sections",
  "GuardianSettingsSection.tsx",
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
  assert.doesNotMatch(
    page,
    /Temporary password|setTemporaryPassword|clipboard/,
  );
  assert.doesNotMatch(
    adminEditor,
    /Temporary password|setTemporaryPassword|clipboard/,
  );
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

test("settings visibility is shared by the navigator and continuous document", () => {
  const nav = readWebFile("components", "settings", "SettingsNav.tsx");
  const settingsPage = readWebFile("app", "(utility)", "settings", "page.tsx");
  const layout = readWebFile("app", "(utility)", "settings", "layout.tsx");

  assert.match(nav, /useSettingsAccess/);
  assert.match(nav, /isSettingsCategoryVisible/);
  assert.match(settingsPage, /useSettingsAccess/);
  assert.match(settingsPage, /isSettingsCategoryVisible/);
  assert.match(settingsPage, /if \(!access\.resolved\)/);
  assert.match(layout, /<SettingsAccessProvider>/);
});

test("learner and guardian sections follow the resolved account type", () => {
  const learner = SETTINGS_CATEGORIES.find(
    (category) => category.key === "learner-profile",
  )!;
  const guardian = SETTINGS_CATEGORIES.find(
    (category) => category.key === "guardian",
  )!;
  const agents = SETTINGS_CATEGORIES.find(
    (category) => category.key === "agents",
  )!;

  assert.equal(
    isSettingsCategoryVisible(learner, PENDING_SETTINGS_ACCESS),
    false,
  );
  assert.equal(
    isSettingsCategoryVisible(guardian, PENDING_SETTINGS_ACCESS),
    false,
  );
  assert.equal(
    isSettingsCategoryVisible(agents, PENDING_SETTINGS_ACCESS),
    false,
  );

  const localAdmin = settingsAccessFromAuthStatus({
    enabled: false,
    authenticated: true,
    is_admin: true,
    preset: "standard",
  });
  assert.equal(isSettingsCategoryVisible(learner, localAdmin), false);
  assert.equal(isSettingsCategoryVisible(guardian, localAdmin), false);
  assert.equal(isSettingsCategoryVisible(agents, localAdmin), true);

  const learnerAccount = settingsAccessFromAuthStatus({
    enabled: true,
    authenticated: true,
    is_admin: false,
    preset: "learner",
  });
  assert.equal(isSettingsCategoryVisible(learner, learnerAccount), true);
  assert.equal(isSettingsCategoryVisible(guardian, learnerAccount), false);
  assert.equal(isSettingsCategoryVisible(agents, learnerAccount), false);

  const guardianAccount = settingsAccessFromAuthStatus({
    enabled: true,
    authenticated: true,
    is_admin: false,
    preset: "standard",
  });
  assert.equal(isSettingsCategoryVisible(learner, guardianAccount), false);
  assert.equal(isSettingsCategoryVisible(guardian, guardianAccount), true);
  assert.equal(isSettingsCategoryVisible(agents, guardianAccount), false);
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
