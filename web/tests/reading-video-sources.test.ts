import test from "node:test";
import assert from "node:assert/strict";

import {
  bilibiliEmbedUrl,
  bilibiliOfficialUrl,
  parseBilibiliSource,
  parseMediaTimestamp,
  youtubeEntryTime,
  youtubeVideoId,
} from "../lib/reading-video-sources";

test("parses supported YouTube source shapes", () => {
  assert.equal(
    youtubeVideoId("https://youtu.be/abc123xyz00?t=82"),
    "abc123xyz00",
  );
  assert.equal(
    youtubeVideoId("https://youtube.com/shorts/abc123xyz00"),
    "abc123xyz00",
  );
  assert.equal(youtubeEntryTime("https://youtu.be/abc123xyz00?t=1m2s"), 62);
});

test("parses Bilibili source, page, and entry time", () => {
  assert.deepEqual(
    parseBilibiliSource(
      "https://www.bilibili.com/video/BV1E7wtzaEdq/?p=2&t=82&spm_id_from=tracking",
    ),
    { bvid: "BV1E7wtzaEdq", page: 2, startSeconds: 82 },
  );
  assert.deepEqual(
    parseBilibiliSource(
      "https://player.bilibili.com/player.html?bvid=BV1E7wtzaEdq&p=3",
    ),
    { bvid: "BV1E7wtzaEdq", page: 3, startSeconds: 0 },
  );
  assert.equal(
    parseBilibiliSource("https://bilibili.com.evil.test/video/BV1E7wtzaEdq"),
    null,
  );
});

test("builds official Bilibili player and timestamp links", () => {
  const source = { bvid: "BV1E7wtzaEdq", page: 1, startSeconds: 0 };
  const embed = new URL(bilibiliEmbedUrl(source, 90));
  assert.equal(embed.origin, "https://player.bilibili.com");
  assert.equal(embed.searchParams.get("bvid"), source.bvid);
  assert.equal(embed.searchParams.get("t"), "90");
  assert.equal(embed.searchParams.get("danmaku"), "0");
  assert.equal(
    bilibiliOfficialUrl(source, 90),
    "https://www.bilibili.com/video/BV1E7wtzaEdq/?t=90",
  );
});

test("parses media timestamps without accepting arbitrary text", () => {
  assert.equal(parseMediaTimestamp("1h2m3s"), 3723);
  assert.equal(parseMediaTimestamp("90"), 90);
  assert.equal(parseMediaTimestamp("later"), 0);
});
