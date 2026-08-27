import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { timedMediaSubtitleUrl } from "../lib/video-learning-api";

test("timed media subtitle URLs stay on the same API origin", () => {
  assert.equal(
    timedMediaSubtitleUrl("material/with:special?id"),
    "/api/v1/video-learning/materials/material%2Fwith%3Aspecial%3Fid/subtitles.vtt"
  );
});

test("the player exposes stored transcript cues as default captions", () => {
  const source = readFileSync(path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"), "utf8");
  assert.match(source, /kind="captions"/);
  assert.match(source, /timedMediaSubtitleUrl\(material\.material_id\)/);
  assert.match(source, /default\b/);
  assert.match(source, /textTracks/);
  assert.match(source, /mode = "showing"/);
  assert.match(source, /requestPictureInPicture/);
  assert.match(source, /webkitpresentationmodechanged/);
  assert.match(source, /data-active/);
  assert.match(source, /aria-current/);
  assert.match(source, /scrollTo/);
});
