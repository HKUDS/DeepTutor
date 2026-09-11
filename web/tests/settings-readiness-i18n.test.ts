import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";

import {
  EXPLAINED_DETAIL_CODES,
  READINESS_SECTION_ORDER,
  READINESS_STATES,
} from "../lib/settings-readiness";

// The readiness panel names almost none of its copy literally: labels come out
// of `readiness.state.<state>`, `readiness.section.<section>` and
// `readiness.detail.<code>`, built from values the backend sends. A key that
// nobody added to the locales therefore does not fail a build or show up in a
// grep — it renders the raw identifier ("readiness.detail.cli_missing") in the
// middle of a Chinese page, which is how this panel shipped its first version
// with English state chips. These tests are the missing compiler.

function findWebRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, "locales", "en", "app.json"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate the web root from " + __dirname);
}

const WEB = findWebRoot();
const PANEL = path.join(WEB, "components/settings/SettingsReadinessPanel.tsx");

function locale(name: string): Record<string, string> {
  return JSON.parse(
    fs.readFileSync(path.join(WEB, "locales", name, "app.json"), "utf8"),
  ) as Record<string, string>;
}

/** Every key the panel can ask for, literal or composed. */
function keysUsed(): string[] {
  const keys = new Set<string>();
  for (const state of READINESS_STATES) keys.add(`readiness.state.${state}`);
  for (const section of READINESS_SECTION_ORDER)
    keys.add(`readiness.section.${section}`);
  for (const code of EXPLAINED_DETAIL_CODES)
    keys.add(`readiness.detail.${code}`);
  const source = fs.readFileSync(PANEL, "utf8");
  for (const match of source.matchAll(/"(readiness\.[a-zA-Z.]+)"/g))
    keys.add(match[1]);
  return [...keys].sort();
}

test("every readiness key exists in both locales", () => {
  const en = locale("en");
  const zh = locale("zh");
  const keys = keysUsed();

  assert.ok(keys.length >= 60, `expected the full key set, found ${keys.length}`);
  const missing = keys.filter((key) => !(key in en) || !(key in zh));
  assert.deepEqual(
    missing,
    [],
    `keys missing from a locale (they render as raw identifiers): ${missing.join(", ")}`,
  );
});

test("readiness copy is really translated into Chinese", () => {
  const en = locale("en");
  const zh = locale("zh");
  const untranslated = keysUsed().filter(
    (key) => zh[key] === en[key] && !/^[\d\s{}n·]*$/.test(en[key] ?? ""),
  );
  assert.deepEqual(
    untranslated,
    [],
    `Chinese still echoes the English: ${untranslated.join(", ")}`,
  );
});

test("every detail code the backend can emit has copy or is a running state", () => {
  // Codes with no sentence are the ones that mean "this row is running", where
  // the Ready label already says everything.
  const RUNNING = new Set([
    "configuration_verified",
    "remote_endpoint_verified",
    "knowledge_base_ready",
    "visualizer_ready",
    "tool_ready",
    "video_provider_ready",
    "coordination_ready",
  ]);
  const source = fs.readFileSync(
    path.join(WEB, "..", "deeptutor/services/config/readiness.py"),
    "utf8",
  );
  const declared = source.slice(
    source.indexOf("DETAIL_CODES: frozenset[str] = frozenset("),
  );
  const codes = [
    ...declared.slice(0, declared.indexOf("\n)")).matchAll(/"([a-z0-9_]+)"/g),
  ].map((match) => match[1]);

  assert.ok(codes.length >= 40, `expected the backend's set, found ${codes.length}`);
  const unexplained = codes.filter(
    (code) => !EXPLAINED_DETAIL_CODES.has(code) && !RUNNING.has(code),
  );
  assert.deepEqual(
    unexplained,
    [],
    `backend codes with no UI sentence: ${unexplained.join(", ")}`,
  );

  // And nothing in the UI set is stale, apart from what the client adds itself.
  const CLIENT_ONLY = new Set(["connection_test_failed"]);
  const stale = [...EXPLAINED_DETAIL_CODES].filter(
    (code) => !codes.includes(code) && !CLIENT_ONLY.has(code),
  );
  assert.deepEqual(stale, [], `UI copy for codes nobody emits: ${stale.join(", ")}`);
});

test("every row label the backend writes itself has copy in both locales", () => {
  // Row labels arrive over the wire and go straight through `t()`, so a label
  // the backend adds without a locale entry renders as English inside a
  // Chinese page — the failure this panel shipped with. Third-party names
  // (parser engines, visualizer manifests) and knowledge base names are not in
  // the declared set: `t()` returning them unchanged is the right answer.
  const en = locale("en");
  const zh = locale("zh");
  const source = fs.readFileSync(
    path.join(WEB, "..", "deeptutor/services/config/readiness.py"),
    "utf8",
  );
  const declared = source.slice(
    source.indexOf("TRANSLATABLE_ROW_LABELS: frozenset[str] = frozenset("),
  );
  const labels = [
    ...declared.slice(0, declared.indexOf("\n)")).matchAll(/"([^"]+)"/g),
  ].map((match) => match[1]);

  assert.ok(labels.length >= 20, `expected the label set, found ${labels.length}`);
  const missing = labels.filter((label) => !(label in en) || !(label in zh));
  assert.deepEqual(
    missing,
    [],
    `row labels missing from a locale: ${missing.join(", ")}`,
  );
});
