import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(relative: string): string {
  return readFileSync(path.resolve(process.cwd(), relative), "utf8");
}

test("the reader exposes exact, fast, and fine search without a second workspace", () => {
  const panel = source("components/reading/ReadingSearchPanel.tsx");
  const reader = source("components/reading/ReaderPane.tsx");

  assert.match(panel, /description_fast/);
  assert.match(panel, /description_fine/);
  assert.match(panel, /Fast search had low confidence/);
  assert.match(reader, /<ReadingSearchPanel/);
  assert.doesNotMatch(reader, /immersive-reading\?/);
});

test("search results jump to their locator and request a five-second source highlight", () => {
  const reader = source("components/reading/ReaderPane.tsx");
  const textReader = source("components/reading/TextUnitView.tsx");

  assert.match(
    reader,
    /rememberExplicitLocation\(locator\);\s*requestJump\(locator, quote, undefined, 5000\);/,
  );
  assert.match(textReader, /dt-reader-search-result/);
  assert.match(textReader, /jump\.highlightMs \?\? 5000/);
});

test("new imports opt into background retrieval-card indexing", () => {
  const api = source("lib/reading-api.ts");

  assert.match(api, /\?build_description_search=true/);
  assert.match(api, /options\?\.reuse === false/);
  assert.match(api, /description-search\/index\/rebuild/);
});
