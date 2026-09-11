import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  settingsAnchorHref,
  storagePathFor,
} from "../features/settings/navigation/settings-nav";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

test("settings navigation: every label targets the unified settings document", () => {
  assert.equal(settingsAnchorHref("overview"), "/settings#overview");
  assert.equal(settingsAnchorHref("llm"), "/settings#llm");
  assert.equal(settingsAnchorHref("about"), "/settings#about");

  const nav = readWebFile("components", "settings", "SettingsNav.tsx");
  assert.match(nav, /settingsAnchorHref\(['"]overview['"]\)/);
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
    "learner-profile",
    "guardian",
    "memory",
    "about",
  ];

  let previousIndex = -1;
  for (const key of keys) {
    const index = Math.max(
      page.indexOf(`key: '${key}'`),
      page.indexOf(`key: "${key}"`),
    );
    assert.ok(
      index > previousIndex,
      `${key} should follow the previous section`,
    );
    previousIndex = index;
  }
});

test("settings scroll: the outer document tracks nested section anchors", () => {
  const source = readWebFile("components", "settings", "CategoryScroll.tsx");
  const scrollHelper = readWebFile(
    "features",
    "settings",
    "navigation",
    "settings-scroll.ts",
  );

  assert.match(source, /data-settings-section-list/);
  assert.match(
    source,
    /querySelectorAll<HTMLElement>\(['"]\[data-settings-section\]['"]\)/,
  );
  assert.match(source, /scrollToSettingsSection/);
  assert.match(source, /ResizeObserver/);
  assert.match(source, /pendingAnchorRef/);
  assert.match(source, /SETTINGS_ANCHOR_EVENT/);
  assert.match(source, /setActiveSection\(current\)/);
  assert.match(source, /requested && !validRequested/);
  assert.match(source, /DeferredSectionContent/);
  assert.match(source, /IntersectionObserver/);
  assert.match(source, /rootMargin: ["']800px 0px["']/);
  assert.match(source, /section\.activationKeys\?\.includes\(requested\)/);
  assert.doesNotMatch(source, /scrollIntoView/);
  assert.match(
    scrollHelper,
    /closest<HTMLElement>\(SETTINGS_SCROLL_SELECTOR\)/,
  );
  assert.match(scrollHelper, /scroller\.scrollTo/);
  assert.match(scrollHelper, /window\.scrollTo/);
  assert.match(scrollHelper, /document\.documentElement\.scrollTop = 0/);
  assert.match(scrollHelper, /requestAnimationFrame\(resetDocumentScroll\)/);
});

test("settings page: heavy sections are split and mounted on demand", () => {
  const page = readWebFile("app", "(utility)", "settings", "page.tsx");
  const models = readWebFile(
    "features",
    "settings",
    "sections",
    "ModelsSettingsSection.tsx",
  );
  const chat = readWebFile(
    "features",
    "settings",
    "sections",
    "ChatSettingsSection.tsx",
  );

  assert.match(page, /dynamic\(/);
  assert.match(page, /deferSections/);
  assert.match(page, /activationKeys: childKeys\(["']models["']\)/);
  assert.match(models, /dynamic\(/);
  assert.match(models, /deferSections/);
  assert.match(chat, /dynamic\(/);
  assert.match(chat, /deferSections/);
});

test("sidebar version badge targets the canonical in-document About section", () => {
  const source = readWebFile("components", "sidebar", "VersionBadge.tsx");

  assert.match(source, /href="\/settings#about"/);
  assert.match(source, /scroll={false}/);
  assert.match(source, /requestSettingsSection\(["']about["']\)/);
  assert.doesNotMatch(source, /\/settings\/about/);
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
