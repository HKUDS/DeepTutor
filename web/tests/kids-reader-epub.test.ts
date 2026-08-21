import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const readerSource = readFileSync(
  path.resolve(process.cwd(), "app/kids/[documentId]/page.tsx"),
  "utf8",
);
const apiSource = readFileSync(path.resolve(process.cwd(), "lib/kids-api.ts"), "utf8");

test("kids reader loads EPUBs through the authorized kids endpoint", () => {
  // react-reader consumes a plain URL, so a raw kids route would not receive
  // the Authorization header kept in localStorage. The blob download closes
  // that gap and keeps original EPUB access behind the child session.
  assert.doesNotMatch(readerSource, /immersive-reading\/documents/);
  assert.match(readerSource, /url=\{epubUrl\}/);
  assert.match(apiSource, /getEpubBlobUrl/);
  assert.match(apiSource, /\/books\/\$\{documentId\}\/epub/);
  assert.match(apiSource, /Authorization.*Bearer/);
});
