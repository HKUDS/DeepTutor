export interface PlaybackRateController {
  getPlaybackRate(): number;
  setPlaybackRate(rate: number): void;
}

export interface PlayerController extends Partial<PlaybackRateController> {
  currentTime(): number;
  duration(): number;
  seek(seconds: number): void;
  play(): void;
  pause(): void;
  destroy(): void;
}

export type PlaybackRateCapableController = PlayerController &
  PlaybackRateController;

export interface YouTubePlayerLike {
  getCurrentTime(): number;
  getDuration(): number;
  getPlaybackRate?(): number;
  setPlaybackRate?(rate: number): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  destroy(): void;
}

export function youtubePlayerController(
  player: YouTubePlayerLike,
): PlaybackRateCapableController {
  return {
    currentTime: () => Number(player.getCurrentTime()) || 0,
    duration: () => Number(player.getDuration()) || 0,
    getPlaybackRate: () => Number(player.getPlaybackRate?.()) || 1,
    setPlaybackRate: (rate) => player.setPlaybackRate?.(rate),
    seek: (seconds) => player.seekTo(Math.max(0, seconds), true),
    play: () => player.playVideo(),
    pause: () => player.pauseVideo(),
    destroy: () => player.destroy(),
  };
}

export function html5PlayerController(
  video: HTMLMediaElement,
): PlaybackRateCapableController {
  return {
    currentTime: () => Number(video.currentTime) || 0,
    duration: () => Number(video.duration) || 0,
    getPlaybackRate: () => Number(video.playbackRate) || 1,
    setPlaybackRate: (rate) => {
      video.playbackRate = rate;
    },
    seek: (seconds) => {
      video.currentTime = Math.max(0, seconds);
    },
    play: () => void video.play(),
    pause: () => video.pause(),
    destroy: () => video.pause(),
  };
}
