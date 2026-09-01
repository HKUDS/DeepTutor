import assert from "node:assert/strict";
import test from "node:test";

import { youtubePlayerController } from "../lib/video-player-controller";

test("normalizes the YouTube IFrame API behind the shared player contract", () => {
  let seeked = -1;
  let played = 0;
  let paused = 0;
  let destroyed = 0;
  const controller = youtubePlayerController({
    getCurrentTime: () => 12.5,
    getDuration: () => 90,
    seekTo: (seconds) => {
      seeked = seconds;
    },
    playVideo: () => {
      played += 1;
    },
    pauseVideo: () => {
      paused += 1;
    },
    destroy: () => {
      destroyed += 1;
    },
  });
  assert.equal(controller.currentTime(), 12.5);
  assert.equal(controller.duration(), 90);
  controller.seek(-3);
  controller.play();
  controller.pause();
  controller.destroy();
  assert.equal(seeked, 0);
  assert.deepEqual([played, paused, destroyed], [1, 1, 1]);
});
