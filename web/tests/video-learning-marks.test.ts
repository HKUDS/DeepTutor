import assert from "node:assert/strict";
import test from "node:test";

import {
  filterMarks,
  formatMarkRange,
  locatorsForRange,
  markCoversTime,
  rangeFromCues,
} from "../lib/video-learning-marks";

const cues = [
  { start: 1, end: 4, text: " first " },
  { start: 5, end: 8, text: "second" },
  { start: 9, end: 12, text: "third" },
];

const segments = cues.map((cue, index) => ({ ...cue, locator: index + 1 }));

test("builds a subtitle range and maps it to segment locators", () => {
  const range = rangeFromCues(cues, [2, 0, 2]);
  assert.ok(range);
  assert.equal(range.start_seconds, 1);
  assert.equal(range.end_seconds, 12);
  assert.equal(range.quote, "first third");
  assert.deepEqual(locatorsForRange(segments, 2, 7), {
    start_locator: 1,
    end_locator: 2,
  });
});

test("filters marks chronologically and matches point and range marks", () => {
  const marks = [
    {
      mark_id: "b",
      kind: "question" as const,
      start_seconds: 8,
      end_seconds: 8,
      start_locator: 2,
      end_locator: 2,
      quote: "",
      note: "",
      author: "user" as const,
      created_at: "2",
      updated_at: "2",
    },
    {
      mark_id: "a",
      kind: "review" as const,
      start_seconds: 1,
      end_seconds: 4,
      start_locator: 1,
      end_locator: 1,
      quote: "",
      note: "",
      author: "user" as const,
      created_at: "1",
      updated_at: "1",
    },
  ];
  assert.deepEqual(filterMarks(marks, "all").map((mark) => mark.mark_id), [
    "a",
    "b",
  ]);
  assert.equal(filterMarks(marks, "review").length, 1);
  assert.equal(markCoversTime(marks[0], 8.5), true);
  assert.equal(markCoversTime(marks[1], 4.5), false);
  assert.equal(formatMarkRange(marks[0]), "00:08");
  assert.equal(formatMarkRange(marks[1]), "00:01 - 00:04");
});
