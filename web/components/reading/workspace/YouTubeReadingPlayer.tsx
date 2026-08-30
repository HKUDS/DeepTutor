"use client";

import { useEffect, useRef } from "react";

import {
  youtubeReadingController,
  type ReadingMediaController,
  type YouTubePlayerLike,
} from "@/lib/reading-media-controller";

interface YouTubeNamespace {
  Player: new (
    element: HTMLElement,
    options: {
      videoId: string;
      host: string;
      width: string;
      height: string;
      playerVars: {
        origin: string;
        playsinline: 1;
        rel: 0;
      };
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

let youtubeApiPromise: Promise<YouTubeNamespace> | null = null;
const YOUTUBE_API_SRC = "https://www.youtube.com/iframe_api";

function loadYouTubeApi(): Promise<YouTubeNamespace> {
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

export function YouTubeReadingPlayer({
  videoId,
  startSeconds,
  title,
  onController,
  onTime,
  onPersist,
  onError,
}: {
  videoId: string;
  startSeconds: number;
  title: string;
  onController(controller: ReadingMediaController | null): void;
  onTime(seconds: number, duration: number): void;
  onPersist(): void;
  onError(error: number | string): void;
}) {
  const playerRootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = playerRootRef.current;
    if (!root) return;
    const mount = document.createElement("div");
    mount.style.width = "100%";
    mount.style.height = "100%";
    root.replaceChildren(mount);
    let cancelled = false;
    let controller: ReadingMediaController | null = null;
    let timer = 0;
    void loadYouTubeApi()
      .then((YT) => {
        if (cancelled) return;
        new YT.Player(mount, {
          videoId,
          host: "https://www.youtube-nocookie.com",
          width: "100%",
          height: "100%",
          playerVars: {
            origin: window.location.origin,
            playsinline: 1,
            rel: 0,
          },
          events: {
            onReady: (event) => {
              if (cancelled) return;
              controller = youtubeReadingController(event.target);
              onController(controller);
              if (startSeconds > 0) controller.seek(startSeconds);
              timer = window.setInterval(
                () =>
                  onTime(
                    controller?.currentTime() || 0,
                    controller?.duration() || 0,
                  ),
                250,
              );
            },
            onStateChange: (event) => {
              if (!cancelled && (event.data === 0 || event.data === 2)) {
                onPersist();
              }
            },
            onError: (event) => {
              if (!cancelled) onError(event.data);
            },
          },
        });
      })
      .catch((caught) => {
        if (!cancelled) {
          onError(
            caught instanceof Error
              ? caught.message
              : "YouTube playback failed.",
          );
        }
      });
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      onController(null);
      controller?.destroy();
      root.replaceChildren();
    };
  }, [onController, onError, onPersist, onTime, startSeconds, videoId]);

  return (
    <div
      ref={playerRootRef}
      className="aspect-video w-full bg-black"
      title={title}
    />
  );
}
