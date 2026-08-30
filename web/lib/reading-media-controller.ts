export interface ReadingMediaController {
  currentTime(): number;
  duration(): number;
  seek(seconds: number): void;
  play(): void;
  pause(): void;
  destroy(): void;
  /**
   * Whether the player reports playback position back to us.
   *
   * Bilibili's external player is a cross-origin iframe with no public
   * JavaScript API: we can start it at a timestamp, but we never learn where
   * it is afterwards. Surfaces that follow playback — the timeline, the
   * "current passage" highlight, resume-where-you-left-off — must say so
   * rather than showing a position that silently never moves.
   */
  tracksPosition: boolean;
}

export interface YouTubePlayerLike {
  getCurrentTime(): number;
  getDuration(): number;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  pauseVideo(): void;
  destroy(): void;
}

export function youtubeReadingController(
  player: YouTubePlayerLike,
): ReadingMediaController {
  return {
    currentTime: () => Number(player.getCurrentTime()) || 0,
    duration: () => Number(player.getDuration()) || 0,
    seek: (seconds) => player.seekTo(Math.max(0, seconds), true),
    play: () => player.playVideo(),
    pause: () => player.pauseVideo(),
    destroy: () => player.destroy(),
    tracksPosition: true,
  };
}

export function html5ReadingController(
  media: HTMLMediaElement,
): ReadingMediaController {
  return {
    currentTime: () => Number(media.currentTime) || 0,
    duration: () => Number(media.duration) || 0,
    seek: (seconds) => {
      media.currentTime = Math.max(0, seconds);
    },
    play: () => void media.play(),
    pause: () => media.pause(),
    destroy: () => media.pause(),
    tracksPosition: true,
  };
}
