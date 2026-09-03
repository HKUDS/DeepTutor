"use client";

import { useEffect, useRef } from "react";

import {
  youtubeReadingController,
  type ReadingMediaController,
} from "@/lib/reading-media-controller";
import { loadYouTubeApi } from "@/lib/youtube-iframe-api";

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
