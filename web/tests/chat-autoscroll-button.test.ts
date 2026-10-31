import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function read(relative: string) {
  return readFileSync(path.resolve(process.cwd(), relative), "utf8");
}

const chat = read("features/chat/components/ChatWorkspace.tsx");
const mastery = read("components/space/learning/MasteryStudy.tsx");
const reading = read("components/reading/workspace/ReadingCompanion.tsx");
const notes = read("features/notes/components/NoteCompanion.tsx");
const button = read("components/chat/ScrollToLatestButton.tsx");

test("chat surfaces gate back-to-latest on detached follow and streaming", () => {
  assert.match(
    chat,
    /<ScrollToLatestButton[\s\S]{0,200}visible=\{isFollowing === false && state\.isStreaming\}/,
  );
  assert.match(
    mastery,
    /<ScrollToLatestButton[\s\S]{0,200}visible=\{isFollowing === false && state\.isStreaming\}/,
  );
});

test("back-to-latest has an accessible label", () => {
  assert.match(button, /aria-label=\{t\("Back to latest"\)\}/);
});

test("companion transcripts delegate scroll intent to the shared hook", () => {
  for (const source of [mastery, reading, notes]) {
    assert.doesNotMatch(
      source,
      /distanceFromBottom\s*<\s*80/,
      "a near-bottom threshold must not re-arm follow on its own",
    );
    assert.match(source, /onScroll=\{(?:handleMessagesScroll|handleScroll)\}/);
  }
});
