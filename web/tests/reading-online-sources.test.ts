import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const webRoot = process.cwd();

function source(relativePath: string): string {
  return readFileSync(path.join(webRoot, relativePath), "utf8");
}

const outline = source("components/reading/ReaderOutline.tsx");
const reader = source("components/reading/ReaderPane.tsx");

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
  assert.match(reader, /dataset\.readerFocus/);
  assert.match(reader, /Show assistant/);
  assert.match(reader, /Hide assistant/);
  assert.match(reader, /event\.key === "Escape"/);
  assert.match(reader, /setFocusMode\(false\)/);
  assert.doesNotMatch(reader, /requestFullscreen\(/);
});

test("reader outline stays left and preserves source hierarchy", () => {
  assert.match(outline, /buildOutlineTree/);
  assert.match(outline, /aria-label=\{t\("Contents"\)\}/);
  assert.match(outline, /absolute inset-y-0 left-0/);
  assert.match(outline, /md:relative/);
  assert.doesNotMatch(outline, /max-h-\[34%\]/);
  assert.match(
    reader,
    /material\?\.source_type === "kb_web_tutorial".*setShowOutline\(true\)/s,
  );
});

test("reader outline switches between source and in-page navigation", () => {
  assert.match(outline, /role="tablist"/);
  assert.match(outline, /sourceType === "kb_web_tutorial"/);
  assert.match(outline, /t\("Website contents"\)/);
  assert.match(outline, /t\("Document contents"\)/);
  assert.match(outline, /filterReaderHeadings/);
  assert.doesNotMatch(outline, /pageHeadings\.length > 0 && \(/);
});

test("in-page heading jumps exclude translations and use container geometry", () => {
  const textReader = source("components/reading/TextUnitView.tsx");

  assert.match(textReader, /data-reader-heading-id/);
  assert.match(textReader, /!element\.closest\("details"\)/);
  assert.match(textReader, /container\.scrollTo\(/);
  assert.match(
    textReader,
    /elementRect\.top -\s*containerRect\.top/,
  );
  assert.doesNotMatch(textReader, /element\.offsetTop - 72/);
});

test("explicit reader jumps keep a session-local back and forward stack", () => {
  assert.match(reader, /pushReadingHistory/);
  assert.match(reader, /goBackReadingHistory/);
  assert.match(reader, /goForwardReadingHistory/);
  assert.match(reader, /event\.altKey/);
  assert.match(reader, /navigateWithHistory\(\{ locator \}\)/);
  assert.doesNotMatch(reader, /history\.pushState/);
});

test("reader preserves source provenance, revisions and migration review", () => {
  const reader = source("components/reading/ReaderPane.tsx");
  const annotations = source("components/reading/AnnotationList.tsx");

  assert.match(reader, /material\.source_url/);
  assert.match(reader, /material\.captured_at/);
  assert.match(reader, /activateMaterialRevision/);
  assert.match(reader, /saveMaterialToKb/);
  assert.match(reader, /getReadingPosition/);
  assert.match(reader, /saveReadingPosition/);
  assert.match(annotations, /migration_status === "needs_review"/);
});

test("reader upgrades the stable URL source and persists local reading preferences", () => {
  const reader = source("components/reading/ReaderPane.tsx");
  const textReader = source("components/reading/TextUnitView.tsx");

  assert.match(reader, /createMaterialFromUrl\(material\.source_ref/);
  assert.match(reader, /whole_tutorial: true/);
  assert.match(textReader, /dt\.reader\.textPreferences/);
  assert.match(textReader, /window\.localStorage\.setItem/);
  assert.match(textReader, /dt-reader-article/);
  assert.match(
    source("app/globals.css"),
    /\.dt-reader-article :where\(\.md-renderer\.prose\)/,
  );
  assert.match(
    source("app/globals.css"),
    /\.dt-reader-article \.md-renderer\.prose h1/,
  );
  assert.match(textReader, /DEFAULT_FONT_SIZE = 17/);
  assert.match(textReader, /MAX_FONT_SIZE = 28/);
  assert.match(textReader, /DEFAULT_LINE_WIDTH = 84/);
  assert.match(textReader, /MAX_LINE_WIDTH = 104/);
  assert.match(textReader, /event\.preventDefault\(\)/);
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
  assert.match(home, /new URLSearchParams\(window\.location\.search\)/);
});
