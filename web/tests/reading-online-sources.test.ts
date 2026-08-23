import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const webRoot = process.cwd();

function source(relativePath: string): string {
  return readFileSync(path.join(webRoot, relativePath), "utf8");
}

test("reading API exposes URL, KB, revision and save-link workflows", () => {
  const api = source("lib/reading-api.ts");

  assert.match(api, /materials\/from-url/);
  assert.match(api, /materials\/from-kb/);
  assert.match(api, /materials\/\$\{materialId\}\/revisions/);
  assert.match(api, /materials\/\$\{materialId\}\/save-to-kb/);
});

test("reader focus mode is application fullscreen and Escape exits", () => {
  const reader = source("components/reading/ReaderPane.tsx");

  assert.match(reader, /fixed inset-0 z-50/);
  assert.match(reader, /event\.key === "Escape"/);
  assert.match(reader, /setFocusMode\(false\)/);
  assert.doesNotMatch(reader, /requestFullscreen\(/);
});

test("reader preserves source provenance, revisions and migration review", () => {
  const reader = source("components/reading/ReaderPane.tsx");
  const annotations = source("components/reading/AnnotationList.tsx");

  assert.match(reader, /material\.source_url/);
  assert.match(reader, /material\.captured_at/);
  assert.match(reader, /activateMaterialRevision/);
  assert.match(reader, /saveMaterialToKb/);
  assert.match(annotations, /migration_status === "needs_review"/);
});

test("KB file and web tutorial actions launch Immersive Reading", () => {
  const preview = source("components/knowledge/KbFilePreview.tsx");
  const webSources = source("components/knowledge/KbWebSourcesSection.tsx");
  const home = source("app/(workspace)/home/[[...sessionId]]/page.tsx");

  assert.match(preview, /createMaterialFromKb/);
  assert.match(webSources, /web_source_id/);
  assert.match(preview, /reading_material=/);
  assert.match(webSources, /reading_material=/);
  assert.match(home, /setCapability\("immersive_reading"\)/);
  assert.match(home, /getReadingMaterial/);
});
