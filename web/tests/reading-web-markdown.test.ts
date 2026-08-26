import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

test("only captured web snapshots use the safe rich Markdown renderer", () => {
  const reader = source("components/reading/ReaderPane.tsx");
  const textReader = source("components/reading/TextUnitView.tsx");
  const picker = source("components/reading/MaterialPicker.tsx");
  const api = source("lib/reading-api.ts");

  assert.match(reader, /contentFormat=\{material\.content_format\}/);
  assert.match(textReader, /contentFormat === "web_markdown"/);
  assert.match(textReader, /allowHtml=\{false\}/);
  assert.match(textReader, /enableImages=\{false\}/);
  assert.match(textReader, /dataset\.readerHeadingId/);
  assert.match(textReader, /TextWithHeadings/);
  assert.match(picker, /createMaterialFromUrl/);
  assert.match(api, /materials\/from-url/);
});
