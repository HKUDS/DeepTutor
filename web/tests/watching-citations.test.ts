import assert from "node:assert/strict";
import test from "node:test";

import {
  linkifyVideoTimestamps,
  videoTimeFromHref,
} from "../lib/watching-citations";

test("linkifies minute and hour timestamp citations", () => {
  assert.equal(
    linkifyVideoTimestamps("See [01:23] and [1:02:03]."),
    "See [01:23](#dt-video-time-83) and [1:02:03](#dt-video-time-3723).",
  );
});

test("preserves code and normalizes existing timestamp links to the current video", () => {
  assert.equal(
    linkifyVideoTimestamps("`[01:23]` [01:23](https://example.test)"),
    "`[01:23]` [01:23](#dt-video-time-83)",
  );
});

test("parses only valid video seek anchors", () => {
  assert.equal(videoTimeFromHref("#dt-video-time-83"), 83);
  assert.equal(videoTimeFromHref("https://example.test"), null);
  assert.equal(videoTimeFromHref("#dt-video-time-nope"), null);
});

test("normalization is idempotent and preserves non-timestamp links", () => {
  const text =
    "[00:28](https://example.com/video?start=28) [source](https://example.com)";
  const normalized = "[00:28](#dt-video-time-28) [source](https://example.com)";
  assert.equal(linkifyVideoTimestamps(text), normalized);
  assert.equal(linkifyVideoTimestamps(normalized), normalized);
});
