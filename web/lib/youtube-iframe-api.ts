import type { YouTubePlayerLike } from "@/lib/video-player-controller";

export interface YouTubeNamespace {
  Player: new (
    element: HTMLElement,
    options: {
      videoId: string;
      host: string;
      width: string;
      height: string;
      playerVars: { origin: string; playsinline: 1; rel: 0 };
      events: {
        onReady(event: { target: YouTubePlayerLike }): void;
        onStateChange(event: { data: number }): void;
        onError(event: { data: number }): void;
      };
    },
  ) => YouTubePlayerLike;
}

declare global {
  interface Window {
    YT?: YouTubeNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

const YOUTUBE_API_SRC = "https://www.youtube.com/iframe_api";
let youtubeApiPromise: Promise<YouTubeNamespace> | null = null;

/** Load the global YouTube IFrame API once for every player surface. */
export function loadYouTubeApi(): Promise<YouTubeNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (youtubeApiPromise) return youtubeApiPromise;

  youtubeApiPromise = new Promise((resolve, reject) => {
    let settled = false;
    const finish = (namespace?: YouTubeNamespace, error?: Error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      if (namespace) resolve(namespace);
      else {
        youtubeApiPromise = null;
        reject(error || new Error("YouTube Player API did not initialize."));
      }
    };
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      try {
        previous?.();
      } finally {
        finish(window.YT?.Player ? window.YT : undefined);
      }
    };
    const timeout = window.setTimeout(
      () => finish(undefined, new Error("YouTube Player API timed out.")),
      10_000,
    );
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${YOUTUBE_API_SRC}"]`,
    );
    const script = existing || document.createElement("script");
    script.addEventListener(
      "error",
      () => {
        script.remove();
        finish(undefined, new Error("YouTube Player API could not be loaded."));
      },
      { once: true },
    );
    if (!existing) {
      script.src = YOUTUBE_API_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
  });

  return youtubeApiPromise;
}
