import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

test("watching pane exposes a public Invidious browse path", () => {
  const pane = readFileSync(
    path.join(process.cwd(), "components/watching/WatchingPane.tsx"),
    "utf8",
  );
  const browse = readFileSync(
    path.join(process.cwd(), "components/watching/InvidiousBrowse.tsx"),
    "utf8",
  );
  const api = readFileSync(
    path.join(process.cwd(), "lib/video-learning-api.ts"),
    "utf8",
  );

  assert.match(pane, /Browse Invidious/);
  assert.match(pane, /<InvidiousBrowse/);
  assert.match(pane, /openHubVideo/);
  assert.doesNotMatch(pane, /TimedMediaReader/);
  assert.doesNotMatch(pane, /connectYouTubeSession/);
  assert.doesNotMatch(browse, /authorize/);
  assert.doesNotMatch(browse, /Subscriptions/);
  assert.match(browse, /Popular/);
  assert.match(browse, /Trending/);
  assert.match(api, /\/api\/v1\/video-learning\/invidious\/home/);
  assert.match(api, /export function youtubeWatchUrl/);
  assert.doesNotMatch(api, /youtube-session/);
});
