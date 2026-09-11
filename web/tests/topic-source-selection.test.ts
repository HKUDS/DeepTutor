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

test("a conversation hydrates to its own kind, not to a knowledge base", async () => {
  // Every kind that is not book/notebook/file used to fall through to
  // `knowledge_base`, which would have filed a transcript as a corpus to
  // search and left the tutor unable to read it.
  const chat: SourceCandidate = {
    key: "chat:sess_1",
    kind: "chat",
    sourceId: "sess_1",
    label: "线性代数答疑",
    detail: "12 messages",
    available: true,
    excerpt: "上次我们聊到特征值",
  };

  assert.deepEqual(await hydrateTopicSource(chat), {
    kind: "chat",
    source_id: "sess_1",
    label: "线性代数答疑",
    excerpt: "上次我们聊到特征值",
    available: true,
  });
});

test("a partner conversation carries the reference form its reader expects", async () => {
  const hydrated = await hydrateTopicSource({
    key: "chat:partner:p1:s9",
    kind: "chat",
    sourceId: "partner:p1:s9",
    label: "和小助教的讨论",
    detail: "8 messages",
    available: true,
  });

  assert.equal(hydrated.kind, "chat");
  assert.equal(hydrated.source_id, "partner:p1:s9");
});

test("a question-bank entry and a draft keep their own kinds", async () => {
  const entry = await hydrateTopicSource({
    key: "question_bank:7",
    kind: "question_bank",
    sourceId: "7",
    label: "特征值的几何意义是什么",
    detail: "Answered wrong",
    available: true,
  });
  assert.equal(entry.kind, "question_bank");
  assert.equal(entry.source_id, "7");

  const draft = await hydrateTopicSource({
    key: "cowriter:doc_1",
    kind: "cowriter",
    sourceId: "doc_1",
    label: "RAG 综述初稿",
    detail: "第一节 检索增强的动机",
    available: true,
  });
  assert.equal(draft.kind, "cowriter");
  assert.equal(draft.source_id, "doc_1");
});
