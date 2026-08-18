import test from "node:test";
import assert from "node:assert/strict";

import {
  defaultReadingView,
  epubHrefsMatch,
  epubReaderOptions,
  immersiveReadingPath,
  normalizeEpubHref,
  resolveStudySectionId,
} from "../lib/epub-reader";
import {
  chineseRevealClassName,
  extractDictionaryWord,
  positionDictionaryPopover,
} from "../lib/dictionary-ui";

test("paginated layout always pairs default manager with paginated flow", () => {
  assert.deepEqual(epubReaderOptions("paginated"), {
    manager: "default",
    flow: "paginated",
  });
});

test("scrolled layout always pairs continuous manager with scrolled flow", () => {
  assert.deepEqual(epubReaderOptions("scrolled"), {
    manager: "continuous",
    flow: "scrolled",
  });
});

test("standard EPUB defaults to original reading unless study is requested", () => {
  assert.equal(defaultReadingView({ sourceFormat: "epub" }), "original");
  assert.equal(defaultReadingView({ sourceFormat: "epub", viewParam: "study" }), "study");
  assert.equal(defaultReadingView({ sourceFormat: "pdf" }), "study");
  assert.equal(defaultReadingView({ sourceFormat: "txt", viewParam: "original" }), "study");
  assert.equal(defaultReadingView({ sourceFormat: "epub", experienceMode: "kids" }), "study");
});

test("href normalization strips relative segments and matches basename", () => {
  assert.equal(normalizeEpubHref("./Text/ch1.xhtml#fn1"), "Text/ch1.xhtml#fn1");
  assert.equal(epubHrefsMatch("OEBPS/chapter-1.xhtml", "chapter-1.xhtml#frag"), true);
  assert.equal(epubHrefsMatch("chapter-1.xhtml", "chapter-2.xhtml"), false);
});

test("study view keeps the current fragment when several sections share an href", () => {
  const sections = [
    { id: "parent", source_href: "chapter-1.xhtml", checkpoint_kind: "none" as const },
    { id: "leaf-a", source_href: "chapter-1.xhtml", checkpoint_kind: "chapter" as const },
    { id: "leaf-b", source_href: "chapter-1.xhtml", checkpoint_kind: "chapter" as const },
  ];
  assert.equal(resolveStudySectionId(sections, "OEBPS/chapter-1.xhtml", "leaf-b"), "leaf-b");
  assert.equal(resolveStudySectionId(sections, "chapter-1.xhtml"), "leaf-a");
});

test("reading path encodes original/study view", () => {
  assert.equal(
    immersiveReadingPath("abc", { view: "original", section: "section_0002" }),
    "/immersive-reading?book=abc&view=original&section=section_0002",
  );
});

test("dictionary selection only accepts one English word", () => {
  assert.equal(extractDictionaryWord("technical"), "technical");
  assert.equal(extractDictionaryWord("technical, "), "technical");
  assert.equal(extractDictionaryWord("technical dynamics"), "");
  assert.equal(extractDictionaryWord("技术"), "");
});

test("dictionary popover chooses available side and clamps to viewport", () => {
  const above = positionDictionaryPopover(
    { left: 180, right: 250, top: 500, bottom: 530 },
    { width: 360, height: 300 },
    { width: 800, height: 600 },
  );
  assert.equal(above.placement, "above");
  assert.equal(above.left, 35);
  assert.equal(above.top, 192);

  const below = positionDictionaryPopover(
    { left: 10, right: 40, top: 10, bottom: 30 },
    { width: 360, height: 300 },
    { width: 400, height: 600 },
  );
  assert.equal(below.placement, "below");
  assert.equal(below.left, 8);
  assert.equal(below.top, 38);
});

test("dictionary Chinese starts visually hidden and becomes clear after reveal", () => {
  const hidden = chineseRevealClassName(false);
  const revealed = chineseRevealClassName(true);

  assert.match(hidden, /blur-\[5px\]/);
  assert.match(hidden, /cursor-pointer/);
  assert.match(hidden, /underline/);
  assert.doesNotMatch(revealed, /blur-\[5px\]/);
  assert.match(revealed, /cursor-default/);
});
