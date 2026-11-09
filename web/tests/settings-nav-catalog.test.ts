import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  SETTINGS_CATEGORIES,
} from "../features/settings/navigation/settings-nav";
import {
  SETTINGS_PAGE_GROUPS,
  settingsPageLabel,
  visibleSettingsPages,
} from "../features/settings/navigation/settings-pages";

// Settings navigation copy renders through t() with the catalog key stored on
// each leaf, category, and group (docs-for-dev/I18N.md). i18next falls back to
// English per key, but a first-class locale is expected to carry every key, so
// these checks keep the navigation free of English-only rows.

const LOCALES = ["en", "zh", "de", "fr", "ja", "pl", "pt", "tr", "uk", "vi"];
const ALL_ACCESS = {
  resolved: true,
  hideAdminOnly: false,
  showLearnerOnly: true,
  showGuardianOnly: true,
};

function catalogKeys(locale: string): Set<string> {
  return new Set(
    Object.keys(
      JSON.parse(
        readFileSync(path.join(process.cwd(), "locales", locale, "app.json"), "utf8"),
      ) as Record<string, string>,
    ),
  );
}

test("settings navigation copy exists in every locale catalog", () => {
  const keys = new Set<string>(["Search results"]);
  for (const group of SETTINGS_PAGE_GROUPS) keys.add(group.label);
  for (const page of visibleSettingsPages(ALL_ACCESS)) {
    keys.add(page.label);
    keys.add(page.blurb);
    keys.add(settingsPageLabel(page.key, page.label));
  }
  for (const category of SETTINGS_CATEGORIES) {
    keys.add(category.label);
    keys.add(category.blurb);
    for (const leaf of category.children ?? []) {
      keys.add(leaf.label);
      keys.add(leaf.blurb);
      keys.add(settingsPageLabel(leaf.key, leaf.label));
    }
  }

  const missing: string[] = [];
  for (const locale of LOCALES) {
    const catalog = catalogKeys(locale);
    for (const key of keys) {
      if (!catalog.has(key)) missing.push(`${locale}: ${JSON.stringify(key)}`);
    }
  }
  assert.deepEqual(
    missing,
    [],
    `add these settings navigation keys to every catalog:\n${missing.join("\n")}`,
  );
});

test("settings navigation copy avoids inline zh/en pairs and language branches", () => {
  const touched = [
    "features/settings/navigation/settings-nav.ts",
    "features/settings/navigation/settings-pages.ts",
    "components/settings/SettingsNav.tsx",
    "components/settings/SettingsPageContent.tsx",
  ];
  for (const file of touched) {
    const source = readFileSync(path.join(process.cwd(), file), "utf8");
    assert.doesNotMatch(
      source,
      /\{\s*(en|zh)\s*:/,
      `${file}: store catalog keys, not inline { en, zh } copy`,
    );
    assert.doesNotMatch(
      source,
      /startsWith\(['"]zh['"]/,
      `${file}: render copy through t() instead of branching on the zh locale`,
    );
  }
});

test("settings search stays bilingual via fixed translators", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/settings/SettingsNav.tsx"),
    "utf8",
  );
  assert.match(
    source,
    /getFixedT\(\s*['"]en['"]/,
    "SettingsNav.tsx: include English terms in search via getFixedT('en')",
  );
  assert.match(
    source,
    /getFixedT\(\s*['"]zh['"]/,
    "SettingsNav.tsx: include Chinese terms in search via getFixedT('zh')",
  );
});
