import {
  html5PlayerController,
  youtubePlayerController,
  type PlayerController,
  type YouTubePlayerLike,
} from "@/lib/video-player-controller";

export interface ReadingMediaController extends PlayerController {
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

export type { YouTubePlayerLike };

function withPositionTracking(
  controller: PlayerController,
): ReadingMediaController {
  return { ...controller, tracksPosition: true };
}

export function youtubeReadingController(
  player: YouTubePlayerLike,
): ReadingMediaController {
  return withPositionTracking(youtubePlayerController(player));
}

export function html5ReadingController(
  media: HTMLMediaElement,
): ReadingMediaController {
  return withPositionTracking(html5PlayerController(media));
}
