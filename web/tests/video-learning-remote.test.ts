import assert from "node:assert/strict";
import test from "node:test";

import { parseVideoIdInput } from "../lib/video-learning-remote-api";

test("remote video parser accepts IDs and YouTube or Invidious watch links", () => {
  assert.equal(parseVideoIdInput("dQw4w9WgXcQ"), "dQw4w9WgXcQ");
  assert.equal(
    parseVideoIdInput("https://youtu.be/dQw4w9WgXcQ?t=12"),
    "dQw4w9WgXcQ",
  );
  assert.equal(
    parseVideoIdInput("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    "dQw4w9WgXcQ",
  );
  assert.equal(
    parseVideoIdInput("https://invidious.example/watch?v=dQw4w9WgXcQ"),
    "dQw4w9WgXcQ",
  );
});

test("remote video parser rejects malformed and non-http input", () => {
  assert.equal(parseVideoIdInput(""), null);
  assert.equal(parseVideoIdInput("short"), null);
  assert.equal(parseVideoIdInput("javascript://youtu.be/dQw4w9WgXcQ"), null);
  assert.equal(parseVideoIdInput("https://example.com/not-watch"), null);
});
