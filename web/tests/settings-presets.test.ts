import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const WEB = process.cwd();

function source(file: string): string {
  return readFileSync(path.join(WEB, file), "utf8");
}

function locale(name: string): Record<string, string> {
  return JSON.parse(
    readFileSync(path.join(WEB, "locales", name, "app.json"), "utf8"),
  ) as Record<string, string>;
}

test("preset drafts reuse the apply flow that owns each setting", () => {
  const endpoints = source("lib/settings-extensions.ts");
  assert.match(endpoints, /"document_parsing": "\/api\/settings\/document-parsing"/);
  assert.match(endpoints, /enabled_tools: "\/api\/settings\/enabled-tools"/);

  const panel = source("components/settings/SettingsPresetsPanel.tsx");
  assert.match(panel, /stagePreset\(preset\.id\)/);
  assert.doesNotMatch(panel, /apiFetch|applyCatalog/);
});

test("staging happens against the draft endpoint, not the apply endpoint", () => {
  const store = source("features/settings/store/SettingsStore.tsx");
  const staged = store.slice(
    store.indexOf("const stagePreset = useCallback("),
    store.indexOf("/** Throw the draft away"),
  );

  assert.match(staged, /\/api\/settings\/presets\/\$\{presetId\}\/draft/);
  assert.match(staged, /method: "POST"/);
  assert.doesNotMatch(staged, /\/api\/settings\/apply/);
});

test("preset copy exists in both locales, including composed keys", () => {
  const en = locale("en");
  const zh = locale("zh");
  const keys = [
    "settings.presets.title",
    "settings.presets.blurb",
    "settings.presets.error",
    "settings.presets.empty",
    "settings.presets.loadDraft",
    "settings.presets.parser",
    "settings.presets.basic_text.name",
    "settings.presets.basic_text.description",
    "settings.presets.local_multimodal.name",
    "settings.presets.local_multimodal.description",
    "settings.presets.university_study.name",
    "settings.presets.university_study.description",
    "settings.presets.full_generation.name",
    "settings.presets.full_generation.description",
    "settings.presets.cost.low",
    "settings.presets.cost.medium",
    "settings.presets.cost.high",
    "settings.presets.credential.llm",
    "settings.presets.credential.imagegen",
    "settings.presets.credential.videogen",
    "settings.presets.prerequisite.llm_profile",
    "settings.presets.prerequisite.markdown_parser",
    "settings.presets.prerequisite.media_profiles",
    "settings.presets.prerequisite.search_profile",
    "settings.presets.feature.core_chat",
    "settings.presets.feature.reasoning",
    "settings.presets.feature.document_parsing",
    "settings.presets.feature.web_search",
    "settings.presets.feature.paper_search",
    "settings.presets.feature.image_generation",
    "settings.presets.feature.video_generation",
  ];

  const missing = keys.filter((key) => !(key in en) || !(key in zh));
  assert.deepEqual(missing, []);
});
