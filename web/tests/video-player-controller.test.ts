import assert from 'node:assert/strict'
import test from 'node:test'

import { html5PlayerController, youtubePlayerController } from '../lib/video-player-controller'

test('normalizes the YouTube IFrame API behind the shared player contract', () => {
  let seeked = -1
  let played = 0
  let paused = 0
  let destroyed = 0
  let playbackRate = 1
  const controller = youtubePlayerController({
    getCurrentTime: () => 12.5,
    getDuration: () => 90,
    getPlaybackRate: () => playbackRate,
    seekTo: seconds => {
      seeked = seconds
    },
    playVideo: () => {
      played += 1
    },
    pauseVideo: () => {
      paused += 1
    },
    setPlaybackRate: rate => {
      playbackRate = rate
    },
    destroy: () => {
      destroyed += 1
    },
  })
  assert.equal(controller.currentTime(), 12.5)
  assert.equal(controller.duration(), 90)
  assert.equal(controller.playbackRate(), 1)
  controller.seek(-3)
  controller.setPlaybackRate(1.5)
  controller.play()
  controller.pause()
  controller.destroy()
  assert.equal(seeked, 0)
  assert.equal(playbackRate, 1.5)
  assert.deepEqual([played, paused, destroyed], [1, 1, 1])
})

test('maps playback rate onto an HTML5 media element', () => {
  let paused = 0
  const media = {
    currentTime: 5,
    duration: 80,
    playbackRate: 1,
    play: async () => undefined,
    pause: () => {
      paused += 1
    },
  } as unknown as HTMLMediaElement
  const controller = html5PlayerController(media)

  controller.setPlaybackRate(1.75)
  assert.equal(controller.playbackRate(), 1.75)
  assert.equal(media.playbackRate, 1.75)

  controller.setPlaybackRate(Number.NaN)
  assert.equal(controller.playbackRate(), 1)
  controller.destroy()
  assert.equal(paused, 1)
})
