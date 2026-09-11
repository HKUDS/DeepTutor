import test from "node:test";
import assert from "node:assert/strict";

import { youtubeReadingController } from "../lib/reading-media-controller";

test("the YouTube adapter clamps seeks and forwards controls", () => {
  const calls: unknown[][] = [];
  const controller = youtubeReadingController({
    getCurrentTime: () => 12.5,
    getDuration: () => 99,
    seekTo: (...args) => calls.push(["seek", ...args]),
    playVideo: () => calls.push(["play"]),
    pauseVideo: () => calls.push(["pause"]),
    destroy: () => calls.push(["destroy"]),
  });

  assert.equal(controller.currentTime(), 12.5);
  assert.equal(controller.duration(), 99);
  controller.seek(-4);
  controller.play();
  controller.pause();
  controller.destroy();
  assert.deepEqual(calls, [
    ["seek", 0, true],
    ["play"],
    ["pause"],
    ["destroy"],
  ]);
});
