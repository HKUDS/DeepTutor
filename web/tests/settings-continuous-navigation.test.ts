import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import { settingsAnchorHref, storagePathFor } from "../lib/settings-nav";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

test("settings navigation: every label targets the unified settings document", () => {
  assert.equal(settingsAnchorHref("overview"), "/settings#overview");
  assert.equal(settingsAnchorHref("llm"), "/settings#llm");
  assert.equal(settingsAnchorHref("about"), "/settings#about");

  const nav = readWebFile("components", "settings", "SettingsNav.tsx");
  assert.match(nav, /settingsAnchorHref\("overview"\)/);
  assert.match(nav, /settingsAnchorHref\(group\.key\)/);
  assert.match(nav, /settingsAnchorHref\(leaf\.key\)/);
});

test("settings page: stacks every first-level section from overview to about", () => {
  const page = readWebFile("app", "(utility)", "settings", "page.tsx");
  const keys = [
    "overview",
    "appearance",
    "network",
    "models",
    "knowledge",
    "chat",
    "agents",
    "memory",
    "about",
  ];

  let previousIndex = -1;
  for (const key of keys) {
    const index = page.indexOf(`key: "${key}"`);
    assert.ok(index > previousIndex, `${key} should follow the previous section`);
    previousIndex = index;
  }
});

test("settings scroll: the outer document tracks nested section anchors", () => {
  const source = readWebFile(
    "components",
    "settings",
    "CategoryScroll.tsx",
  );

  assert.match(source, /data-settings-section-list/);
  assert.match(source, /querySelectorAll<HTMLElement>\("\[data-settings-section\]"\)/);
  assert.match(source, /scrollIntoView/);
  assert.match(source, /setActiveSection\(current\)/);
});

test("settings toolbar: resolves storage paths while scrolling the unified page", () => {
  assert.equal(
    storagePathFor("/settings", "network"),
    "data/user/settings/system.json",
  );
  assert.equal(
    storagePathFor("/settings", "connections"),
    "data/user/settings/model_catalog.json",
  );
  assert.equal(
    storagePathFor("/settings", "knowledge"),
    "data/user/settings/document_parsing.json",
  );
  assert.equal(storagePathFor("/settings", "about"), null);
});
