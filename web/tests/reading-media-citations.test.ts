import test from "node:test";
import assert from "node:assert/strict";

import {
  MEDIA_TIME_HREF_PREFIX,
  linkifyMediaTimestamps,
  mediaTimeFromHref,
} from "../lib/reading-media-citations";

test("linkifies minute and hour timestamps", () => {
  assert.equal(
    linkifyMediaTimestamps("Compare [01:12] with [1:02:03]."),
    `Compare [01:12](${MEDIA_TIME_HREF_PREFIX}72) with [1:02:03](${MEDIA_TIME_HREF_PREFIX}3723).`,
  );
});

test("does not rewrite code or existing links", () => {
  assert.equal(linkifyMediaTimestamps("Use `[01:12]`."), "Use `[01:12]`.");
  assert.equal(
    linkifyMediaTimestamps("[01:12](https://example.com)"),
    "[01:12](https://example.com)",
  );
});

test("extracts only valid reading media anchors", () => {
  assert.equal(mediaTimeFromHref(`${MEDIA_TIME_HREF_PREFIX}72`), 72);
  assert.equal(mediaTimeFromHref(`${MEDIA_TIME_HREF_PREFIX}-1`), null);
  assert.equal(mediaTimeFromHref("#other"), null);
  assert.equal(mediaTimeFromHref(null), null);
});
