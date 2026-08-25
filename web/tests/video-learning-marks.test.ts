import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import type { TimedCue, TimedSegment, VideoLearningMark } from "../lib/video-learning-api";
import {
  cueIndexesFromSelection,
  filterMarks,
  formatMarkRange,
  locatorsForRange,
  markCoversTime,
  marksAtTime,
  rangeFromCues,
  sortMarks,
  timelineStyle,
  uniqueSortedIndexes,
} from "../lib/video-learning-marks";

const cues: TimedCue[] = [
  { start: 10, end: 16, text: "Gradient descent" },
  { start: 16, end: 24, text: "finds a local minimum." },
  { start: 40, end: 48, text: "Review this example." },
];

const segments: TimedSegment[] = [
  { locator: 1, start: 10, end: 24, text: "Gradient descent finds a local minimum." },
  { locator: 2, start: 40, end: 48, text: "Review this example." },
];

const marks: VideoLearningMark[] = [
  {
    mark_id: "a",
    kind: "review",
    start_seconds: 40,
    end_seconds: 48,
    start_locator: 2,
    end_locator: 2,
    quote: "Review this example.",
    note: "",
    author: "user",
    created_at: "1",
    updated_at: "1",
  },
  {
    mark_id: "b",
    kind: "key_point",
    start_seconds: 10,
    end_seconds: 24,
    start_locator: 1,
    end_locator: 1,
    quote: "Gradient descent finds a local minimum.",
    note: "",
    author: "user",
    created_at: "1",
    updated_at: "1",
  },
  {
    mark_id: "c",
    kind: "question",
    start_seconds: 18,
    end_seconds: 18,
    start_locator: 1,
    end_locator: 1,
    quote: "finds a local minimum.",
    note: "",
    author: "assistant",
    created_at: "1",
    updated_at: "1",
  },
];

test("rangeFromCues uses earliest start and latest end", () => {
  const range = rangeFromCues(cues, [1, 0, 0]);
  assert.deepEqual(range, {
    start_seconds: 10,
    end_seconds: 24,
    quote: "Gradient descent finds a local minimum.",
  });
  assert.equal(rangeFromCues(cues, []), null);
});

test("locatorsForRange maps a subtitle span onto semantic segments", () => {
  assert.deepEqual(locatorsForRange(segments, 10, 24), { start_locator: 1, end_locator: 1 });
  assert.deepEqual(locatorsForRange(segments, 10, 48), { start_locator: 1, end_locator: 2 });
});

test("point bookmarks match nearby playback and range marks match interiors", () => {
  assert.equal(markCoversTime(marks[2], 18.4), true);
  assert.equal(markCoversTime(marks[2], 22), false);
  assert.equal(markCoversTime(marks[1], 20), true);
  assert.equal(marksAtTime(marks, 18).map((mark) => mark.mark_id).join(","), "b,c");
});

test("filterMarks sorts by time and keeps a kind filter", () => {
  assert.deepEqual(sortMarks(marks).map((mark) => mark.mark_id), ["b", "c", "a"]);
  assert.deepEqual(filterMarks(marks, "review").map((mark) => mark.mark_id), ["a"]);
  assert.equal(filterMarks([], "all").length, 0);
});

test("timelineStyle keeps a visible tick for zero-width bookmarks", () => {
  const point = timelineStyle(marks[2], 100);
  assert.equal(point.left, "18%");
  assert.equal(point.width, "0.8%");
  const range = timelineStyle(marks[1], 100);
  assert.equal(range.left, "10%");
  assert.equal(range.width, "14%");
});

test("formatMarkRange distinguishes bookmarks from ranges", () => {
  assert.equal(formatMarkRange(marks[2]), "00:18");
  assert.equal(formatMarkRange(marks[1]), "00:10 – 00:24");
});

test("uniqueSortedIndexes drops negatives and duplicates", () => {
  assert.deepEqual(uniqueSortedIndexes([2, 2, -1, 0, 1.5, 1]), [0, 2, 1].sort((a, b) => a - b));
});

test("cueIndexesFromSelection ignores collapsed or foreign selections", () => {
  assert.deepEqual(cueIndexesFromSelection(null, null), []);
  const selection = {
    rangeCount: 0,
    isCollapsed: true,
    getRangeAt() {
      throw new Error("unused");
    },
  } as unknown as Selection;
  assert.deepEqual(cueIndexesFromSelection({} as ParentNode, selection), []);
});

test("transcript rows expose selectable text instead of a whole-row seek button", () => {
  const source = readFileSync(path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"), "utf8");
  assert.match(source, /data-cue-index/);
  assert.match(source, /select-text/);
  assert.match(source, /Extract key points/);
  assert.match(source, /Set start/);
  assert.match(source, /LearningTimeline/);
  assert.match(source, /KeyPointsPanel/);
  assert.doesNotMatch(
    source,
    /cues\.map\(\(cue, index\) => \(\s*<button[\s\S]*seek\(cue\.start\)[\s\S]*cue\.text/,
  );
});
