export interface PlayerController {
  currentTime(): number;
  duration(): number;
  seek(seconds: number): void;
  play(): void;
  pause(): void;
  destroy(): void;
}

export interface YouTubePlayerLike {
  getCurrentTime(): number;
  getDuration(): number;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  destroy(): void;
}

export function youtubePlayerController(
  player: YouTubePlayerLike,
): PlayerController {
  return {
    currentTime: () => Number(player.getCurrentTime()) || 0,
    duration: () => Number(player.getDuration()) || 0,
    seek: (seconds) => player.seekTo(Math.max(0, seconds), true),
    play: () => player.playVideo(),
    pause: () => player.pauseVideo(),
    destroy: () => player.destroy(),
  };
}

export function html5PlayerController(
  video: HTMLMediaElement,
): PlayerController {
  return {
    currentTime: () => Number(video.currentTime) || 0,
    duration: () => Number(video.duration) || 0,
    seek: (seconds) => {
      video.currentTime = Math.max(0, seconds);
    },
    play: () => void video.play(),
    pause: () => video.pause(),
    destroy: () => video.pause(),
  };
}
