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

test("does not rewrite code or existing links", () => {
  assert.equal(
    linkifyVideoTimestamps("`[01:23]` [01:23](https://example.test)"),
    "`[01:23]` [01:23](https://example.test)",
  );
});

test("parses only valid video seek anchors", () => {
  assert.equal(videoTimeFromHref("#dt-video-time-83"), 83);
  assert.equal(videoTimeFromHref("https://example.test"), null);
  assert.equal(videoTimeFromHref("#dt-video-time-nope"), null);
});
