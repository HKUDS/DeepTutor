import test from "node:test";
import assert from "node:assert/strict";
import {
  settingsAnchorHref,
  storagePathFor,
  SETTINGS_CATEGORIES,
} from "../features/settings/navigation/settings-nav";
import {
  legacySettingsDestination,
  visibleSettingsPages,
  settingsPageFamily,
  SETTINGS_PAGE_GROUPS,
} from "../features/settings/navigation/settings-pages";

const admin = {
  resolved: true,
  hideAdminOnly: false,
  showLearnerOnly: false,
  showGuardianOnly: false,
};

test("legacy settings bookmarks resolve to independent pages, preserving profile links", () => {
  assert.equal(legacySettingsDestination("", ""), "/settings/general");
  assert.equal(legacySettingsDestination("#overview", ""), "/settings/general");
  assert.equal(
    legacySettingsDestination("#document-parsing", ""),
    "/settings/knowledge",
  );
  assert.equal(
    legacySettingsDestination("#llm?profile=old%20id", ""),
    "/settings/llm?profile=old+id",
  );
  assert.equal(
    legacySettingsDestination("#llm", "?profile=old-id"),
    "/settings/llm?profile=old-id",
  );
  assert.equal(legacySettingsDestination("#%invalid", ""), "/settings/general");
  for (const category of SETTINGS_CATEGORIES) {
    for (const leaf of category.children ?? [category]) {
      assert.equal(
        legacySettingsDestination(`#${leaf.key}`, ""),
        settingsAnchorHref(leaf.key),
      );
    }
  }
});

test("every available setting is reachable through a navigation family", () => {
  const reachable = new Set(
    SETTINGS_PAGE_GROUPS.flatMap(group =>
      group.keys.flatMap(settingsPageFamily),
    ),
  );
  for (const page of visibleSettingsPages({
    ...admin,
    showLearnerOnly: true,
    showGuardianOnly: true,
  })) {
    assert.ok(reachable.has(page.key), page.key);
  }
});

test("restricted pages stay hidden, including when searched or linked directly", () => {
  const keys = visibleSettingsPages({
    ...admin,
    hideAdminOnly: true,
    showLearnerOnly: true,
  }).map(page => page.key);
  assert.ok(keys.includes("learner-profile"));
  assert.ok(!keys.includes("guardian"));
  assert.ok(!keys.includes("attachments"));
  assert.ok(!keys.includes("agent-codex"));
});

test("settings routes expose their configuration storage destinations", () => {
  assert.equal(storagePathFor("/settings/workspace"), "data/user/.runtime/workspaces.sqlite3");
  for (const [key, file] of Object.entries({
    network: "system.json",
    connections: "model_catalog.json",
    llm: "model_catalog.json",
    "task-models": "model_catalog.json",
    embedding: "model_catalog.json",
    knowledge: "document_parsing.json",
    general: "interface.json",
    "agent-codex": "subagent.json",
  }))
    assert.equal(
      storagePathFor(`/settings/${key}`),
      `data/user/settings/${file}`,
    );
  assert.equal(
    storagePathFor("/settings", "network"),
    "data/user/settings/system.json",
  );
  assert.equal(storagePathFor("/settings/about"), null);
});


test("voice and generation have independent pages and legacy destinations", () => {
  const keys = visibleSettingsPages(admin).map(page => page.key);
  assert.ok(keys.includes("voice"));
  assert.ok(keys.includes("multimodal"));
  for (const key of ["tts", "stt"]) {
    assert.equal(settingsAnchorHref(key), "/settings/voice");
    assert.equal(legacySettingsDestination(`#${key}`, "?profile=saved"), "/settings/voice?profile=saved");
  }
  for (const key of ["image", "video", "imagegen", "videogen"]) {
    assert.equal(settingsAnchorHref(key), "/settings/multimodal");
  }
  for (const key of ["voice", "multimodal", "tts", "stt", "imagegen", "videogen"]) {
    assert.equal(storagePathFor(`/settings/${key}`), "data/user/settings/model_catalog.json");
  }
});
