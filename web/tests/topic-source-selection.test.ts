import test from "node:test";
import assert from "node:assert/strict";

import {
  hydrateTopicSource,
  toggleSourceSelection,
  type SourceCandidate,
} from "../hooks/useTopicSourceLibrary";

const LIBRARY: SourceCandidate = {
  key: "knowledge_base:course",
  kind: "knowledge_base",
  sourceId: "course",
  label: "course",
  detail: "Ready to retrieve",
  available: true,
};

function file(name: string): SourceCandidate {
  return {
    key: `file:course:${name}`,
    kind: "file",
    sourceId: name,
    label: name,
    detail: "File in course",
    available: true,
    kbName: "course",
    path: name,
    parentKey: LIBRARY.key,
  };
}

const CANDIDATES = [LIBRARY, file("week01.pdf"), file("week02.pdf")];

test("selecting a whole library drops the files picked out of it", () => {
  // Both would send the same material twice — once retrieved, once extracted
  // — and count it twice when coverage is measured.
  const selected = new Set(["file:course:week01.pdf", "file:course:week02.pdf"]);

  const next = toggleSourceSelection(selected, LIBRARY.key, CANDIDATES);

  assert.deepEqual([...next], [LIBRARY.key]);
});

test("selecting one file leaves the other files alone", () => {
  const next = toggleSourceSelection(
    new Set(["file:course:week02.pdf"]),
    "file:course:week01.pdf",
    CANDIDATES,
  );

  assert.equal(next.size, 2);
  assert.ok(next.has("file:course:week01.pdf"));
  assert.ok(next.has("file:course:week02.pdf"));
});

test("a file from another library is untouched", () => {
  const other: SourceCandidate = {
    ...file("intro.pdf"),
    key: "file:stats:intro.pdf",
    kbName: "stats",
    parentKey: "knowledge_base:stats",
  };

  const next = toggleSourceSelection(
    new Set(["file:stats:intro.pdf"]),
    LIBRARY.key,
    [...CANDIDATES, other],
  );

  assert.ok(next.has("file:stats:intro.pdf"));
  assert.ok(next.has(LIBRARY.key));
});

test("toggling an already-selected key removes it and nothing else", () => {
  const next = toggleSourceSelection(
    new Set([LIBRARY.key, "file:stats:intro.pdf"]),
    LIBRARY.key,
    CANDIDATES,
  );

  assert.deepEqual([...next], ["file:stats:intro.pdf"]);
});

test("a picked file travels as an address, not an excerpt", async () => {
  // The browser cannot read a PDF out of a knowledge base; the server
  // extracts the text while grounding the outline.
  const source = await hydrateTopicSource(file("slides/week03.pdf"));

  assert.equal(source.kind, "file");
  assert.equal(source.source_id, "slides/week03.pdf");
  assert.equal(source.excerpt, "");
  assert.deepEqual(source.metadata, {
    kb_name: "course",
    path: "slides/week03.pdf",
  });
});

test("a whole library still travels as a knowledge_base source", async () => {
  const source = await hydrateTopicSource(LIBRARY);

  assert.equal(source.kind, "knowledge_base");
  assert.equal(source.source_id, "course");
});
