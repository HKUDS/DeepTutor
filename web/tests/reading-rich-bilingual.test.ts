import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const textView = readFileSync(
  resolve(process.cwd(), "components/reading/TextUnitView.tsx"),
  "utf8",
);
const epubView = readFileSync(
  resolve(process.cwd(), "components/reading/EpubDocumentView.tsx"),
  "utf8",
);

test("Markdown reading is explicitly safe and no longer rendered as pre-wrapped text", () => {
  assert.match(textView, /contentFormat === "markdown"/);
  assert.match(textView, /<MarkdownRenderer/);
  assert.match(textView, /allowHtml=\{false\}/);
});

test("web bilingual blocks start collapsed and expose per-block and global controls", () => {
  assert.match(textView, /new Set\(\)/);
  assert.match(textView, /<details/);
  assert.match(textView, /Show Chinese/);
  assert.match(textView, /Expand all Chinese/);
  assert.match(textView, /low_confidence/);
});

test("EPUB bilingual pairing requires an explicit candidate confirmation", () => {
  assert.match(epubView, /listEpubPairingCandidates/);
  assert.match(epubView, /confirmPairing\(candidate\.material_id\)/);
  assert.match(epubView, /Confirm a recommended edition/);
  assert.match(epubView, /translationsExpandedRef\.current = false/);
});
