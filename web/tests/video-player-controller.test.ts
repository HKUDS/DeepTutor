import assert from "node:assert/strict";
import test from "node:test";

import {
  html5PlayerController,
  youtubePlayerController,
} from "../lib/video-player-controller";

test("normalizes the YouTube IFrame API behind the shared player contract", () => {
  let seeked = -1;
  let playbackRate = 1;
  let played = 0;
  let paused = 0;
  let destroyed = 0;
  const controller = youtubePlayerController({
    getCurrentTime: () => 12.5,
    getDuration: () => 90,
    getPlaybackRate: () => playbackRate,
    setPlaybackRate: (rate) => {
      playbackRate = rate;
    },
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
  controller.setPlaybackRate(1.5);
  assert.equal(controller.getPlaybackRate(), 1.5);
  controller.seek(-3);
  controller.play();
  controller.pause();
  controller.destroy();
  assert.equal(seeked, 0);
  assert.deepEqual([played, paused, destroyed], [1, 1, 1]);
});

test("maps HTML5 playback rate behind the shared player contract", () => {
  const video = {
    currentTime: 4,
    duration: 48,
    playbackRate: 1,
    play: () => undefined,
    pause: () => undefined,
  } as unknown as HTMLMediaElement;
  const controller = html5PlayerController(video);

  assert.equal(controller.getPlaybackRate(), 1);
  controller.setPlaybackRate(0.75);
  assert.equal(video.playbackRate, 0.75);
  assert.equal(controller.getPlaybackRate(), 0.75);
});
