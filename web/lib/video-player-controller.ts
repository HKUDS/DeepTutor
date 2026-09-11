export interface PlayerController {
  currentTime(): number
  duration(): number
  playbackRate(): number
  seek(seconds: number): void
  setPlaybackRate(rate: number): void
  play(): void
  pause(): void
  destroy(): void
}

export interface YouTubePlayerLike {
  getCurrentTime(): number
  getDuration(): number
  getPlaybackRate?(): number
  seekTo(seconds: number, allowSeekAhead: boolean): void
  setPlaybackRate?(rate: number): void
  playVideo(): void
  pauseVideo(): void
  destroy(): void
}

export const DEFAULT_PLAYBACK_RATE = 1
export const WATCHING_PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2] as const

function normalizePlaybackRate(rate: number): number {
  const parsed = Number(rate)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_PLAYBACK_RATE
}

export function youtubePlayerController(player: YouTubePlayerLike): PlayerController {
  return {
    currentTime: () => Number(player.getCurrentTime()) || 0,
    duration: () => Number(player.getDuration()) || 0,
    playbackRate: () => normalizePlaybackRate(player.getPlaybackRate?.() ?? DEFAULT_PLAYBACK_RATE),
    seek: seconds => player.seekTo(Math.max(0, seconds), true),
    setPlaybackRate: rate => player.setPlaybackRate?.(normalizePlaybackRate(rate)),
    play: () => player.playVideo(),
    pause: () => player.pauseVideo(),
    destroy: () => player.destroy(),
  }
}

export function html5PlayerController(video: HTMLMediaElement): PlayerController {
  return {
    currentTime: () => Number(video.currentTime) || 0,
    duration: () => Number(video.duration) || 0,
    playbackRate: () => normalizePlaybackRate(video.playbackRate),
    seek: seconds => {
      video.currentTime = Math.max(0, seconds)
    },
    setPlaybackRate: rate => {
      video.playbackRate = normalizePlaybackRate(rate)
    },
    play: () => void video.play(),
    pause: () => video.pause(),
    destroy: () => video.pause(),
  }
}
