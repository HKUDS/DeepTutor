import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

test("web snapshots and uploaded Markdown use the safe rich Markdown renderer", () => {
  const reader = fs.readFileSync(
    path.join(process.cwd(), "components/reading/TextUnitView.tsx"),
    "utf8",
  );
  const pane = fs.readFileSync(
    path.join(process.cwd(), "components/reading/ReaderPane.tsx"),
    "utf8",
  );

  assert.match(reader, /contentFormat === "web_markdown"/);
  assert.match(reader, /<RichMarkdownRenderer/);
  assert.match(reader, /allowHtml=\{false\}/);
  assert.match(reader, /enableImages=\{sourceType !== "upload"\}/);
  assert.match(reader, /whitespace-pre-wrap/);
  assert.match(pane, /contentFormat=\{material\.content_format\}/);
  assert.match(pane, /sourceType=\{material\.source_type\}/);
});
