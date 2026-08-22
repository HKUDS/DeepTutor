import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { resolveKidsReadingSectionId } from "../lib/kids-api";

const readerSource = readFileSync(
  path.resolve(process.cwd(), "app/kids/[documentId]/page.tsx"),
  "utf8",
);
const apiSource = readFileSync(path.resolve(process.cwd(), "lib/kids-api.ts"), "utf8");
const globalCss = readFileSync(path.resolve(process.cwd(), "app/globals.css"), "utf8");

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

test("kids reader centers guided learning and demotes translation", () => {
  assert.match(readerSource, /Look and Think/);
  assert.match(readerSource, /Think again/);
  assert.match(readerSource, />\s*Learn\s*</);
  assert.match(readerSource, />\s*Quiz\s*</);
  assert.match(readerSource, /result\.total_stars/);
  assert.doesNotMatch(readerSource, />\s*Translate\s*</);
  assert.match(readerSource, /Languages/);
});

test("kids reader always offers three guided questions with pronunciation", () => {
  assert.match(readerSource, /Getting 3 questions/);
  assert.match(readerSource, /speakQuizText/);
  assert.match(readerSource, /question-\$\{qi\}/);
  assert.match(readerSource, /choice-\$\{qi\}-\$\{ci\}/);
  assert.match(readerSource, /answer-\$\{i\}/);
  assert.match(readerSource, /Volume2/);
  assert.match(readerSource, /shouldOpenChapterCheck/);
  assert.match(readerSource, /loadLearnQuestions\(sectionId\)/);
});

test("kids reader protects the restored learning golden path", () => {
  assert.match(readerSource, /kidsApi\.getWordHint/);
  assert.match(readerSource, /createInitialWordHintState/);
  assert.match(readerSource, /reduceWordHintState/);
  assert.match(readerSource, /decorateEpubWords/);
  assert.match(readerSource, /data-kids-word/);
  assert.match(readerSource, /hint-clue/);
  assert.match(readerSource, /Read thinking clue/);
  assert.match(readerSource, /locations\.generate\(256\)/);
  assert.match(readerSource, /reportLocation/);
  assert.match(readerSource, /speakKidsText/);
  assert.match(readerSource, /stopKidsSpeech/);
  assert.match(readerSource, /shownSectionIdsRef/);
  assert.match(readerSource, /handleReadAloud/);
  assert.match(readerSource, /getVisiblePageText/);
  assert.doesNotMatch(readerSource, /speechSynthesis/);
});

test("kids reader keeps actions inside the iPad dynamic viewport", () => {
  assert.match(readerSource, /className="kids-reader-shell"/);
  assert.match(readerSource, /className="kids-reader-actions"/);
  assert.doesNotMatch(readerSource, /style=\{\{ height: "100vh"/);
  assert.match(globalCss, /\.kids-reader-shell\s*\{/);
  assert.match(globalCss, /height:\s*100dvh/);
  assert.match(globalCss, /\.kids-reader-actions\s*\{/);
  assert.match(globalCss, /padding-bottom:\s*max\(10px,\s*env\(safe-area-inset-bottom\)\)/);
});

test("kids reader maps EPUB navigation to backend reading sections", () => {
  const sections = [
    { id: "section_0004", title: "Contents", index: 3, checkpoint_kind: "none" },
    { id: "section_0005", title: "Book 1 - Plums", index: 4, checkpoint_kind: "chapter" },
    { id: "section_0006", title: "Book 2 - Little Bug", index: 5, checkpoint_kind: "chapter" },
    {
      id: "section_0007",
      title: "Explicit href",
      index: 6,
      checkpoint_kind: "chapter",
      source_href: "OEBPS/explicit.xhtml",
    },
  ];

  const sectionId = resolveKidsReadingSectionId(
    "OEBPS/chap01.html",
    [{ href: "../Text/chap01.html", label: "Book 1 - Plums" }],
    sections,
  );

  assert.equal(sectionId, "section_0005");
  assert.equal(resolveKidsReadingSectionId("OEBPS/chap02.html", [], sections), "section_0006");
  assert.equal(resolveKidsReadingSectionId("OEBPS/explicit.xhtml", [], sections), "section_0007");
  assert.equal(resolveKidsReadingSectionId("unknown.html", [], []), "");
});
