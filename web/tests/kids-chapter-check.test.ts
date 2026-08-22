import test from "node:test";
import assert from "node:assert/strict";

import { shouldOpenChapterCheck } from "../lib/kids-learning/chapter-check";

test("opens a chapter check at the final page", () => {
  assert.equal(
    shouldOpenChapterCheck({
      currentSectionId: "section-1",
      sectionKind: "chapter",
      atEnd: true,
      percentage: 0,
      completedSectionIds: [],
      shownSectionIds: [],
    }),
    "current",
  );
});

test("opens a chapter check at ninety-eight percent", () => {
  assert.equal(
    shouldOpenChapterCheck({
      currentSectionId: "section-1",
      sectionKind: "chapter",
      atEnd: false,
      percentage: 0.98,
      completedSectionIds: [],
      shownSectionIds: [],
    }),
    "current",
  );
});

test("opens the previous chapter when entering the next one", () => {
  assert.equal(
    shouldOpenChapterCheck({
      currentSectionId: "section-2",
      previousSectionId: "section-1",
      previousSectionKind: "chapter",
      sectionKind: "none",
      atEnd: false,
      percentage: 0,
      completedSectionIds: [],
      shownSectionIds: [],
    }),
    "previous",
  );
});

test("does not repeatedly open the same chapter check", () => {
  assert.equal(
    shouldOpenChapterCheck({
      currentSectionId: "section-1",
      sectionKind: "chapter",
      atEnd: true,
      percentage: 0,
      completedSectionIds: [],
      shownSectionIds: ["section-1"],
    }),
    null,
  );
  assert.equal(
    shouldOpenChapterCheck({
      currentSectionId: "section-1",
      previousSectionId: "section-1",
      previousSectionKind: "chapter",
      sectionKind: "chapter",
      atEnd: true,
      percentage: 1,
      completedSectionIds: ["section-1"],
      shownSectionIds: ["section-1"],
    }),
    null,
  );
});
