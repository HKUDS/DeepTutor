import assert from "node:assert/strict";
import test from "node:test";

import {
  formatWatchClock,
  parseTimedMediaRef,
  watchingJumpHref,
} from "../lib/video-learning-kb";

test("parseTimedMediaRef reads material and range", () => {
  const parsed = parseTimedMediaRef("abc123#t=12.5-18");
  assert.deepEqual(parsed, {
    materialId: "abc123",
    startSeconds: 12.5,
    endSeconds: 18,
  });
});

test("watchingJumpHref builds home deep link", () => {
  assert.equal(
    watchingJumpHref("abc123", 12.5),
    "/home?watching_material=abc123&t=12.5",
  );
  assert.equal(formatWatchClock(75), "1:15");
});
