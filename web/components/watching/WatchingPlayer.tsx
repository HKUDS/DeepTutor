"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { apiUrl } from "@/lib/api";
import {
  html5PlayerController,
  youtubePlayerController,
  type PlayerController,
} from "@/lib/video-player-controller";
import type { VideoPlayback } from "@/lib/video-learning-api";
import { loadYouTubeApi } from "@/lib/youtube-iframe-api";

interface WatchingPlayerProps {
  playback: VideoPlayback;
  transcriptLanguage: string;
  onController(controller: PlayerController | null): void;
  onTime(seconds: number, duration: number): void;
  onPersist(): void;
  onError(message: string): void;
}

export function WatchingPlayer(props: WatchingPlayerProps) {
  return props.playback.kind === "youtube_iframe" ? (
    <YouTubePlayer {...props} playback={props.playback} />
  ) : (
    <InvidiousPlayer {...props} playback={props.playback} />
  );
}

function YouTubePlayer({
  playback,
  onController,
  onTime,
  onPersist,
  onError,
}: WatchingPlayerProps & {
  playback: Extract<VideoPlayback, { kind: "youtube_iframe" }>;
}) {
  const { t } = useTranslation();
  const playerRootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const playerRoot = playerRootRef.current;
    if (!playerRoot) return;
    const mount = document.createElement("div");
    mount.style.width = "100%";
    mount.style.height = "100%";
    playerRoot.replaceChildren(mount);
    let cancelled = false;
    let controller: PlayerController | null = null;
    let timer = 0;
    void loadYouTubeApi()
      .then((YT) => {
        if (cancelled) return;
        new YT.Player(mount, {
          videoId: playback.video_id,
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
              controller = youtubePlayerController(event.target);
              onController(controller);
              if (playback.start_seconds > 0)
                controller.seek(playback.start_seconds);
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
              if (cancelled) return;
              if (event.data === 0 || event.data === 2) onPersist();
            },
            onError: (event) => {
              if (!cancelled)
                onError(
                  t("YouTube playback failed ({{code}}).", {
                    code: event.data,
                  }),
                );
            },
          },
        });
      })
      .catch((caught) => {
        if (!cancelled) {
          onError(
            caught instanceof Error
              ? t(caught.message)
              : t("YouTube playback failed."),
          );
        }
      });
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      onController(null);
      controller?.destroy();
      playerRoot.replaceChildren();
    };
  }, [
    onController,
    onError,
    onPersist,
    onTime,
    playback.start_seconds,
    playback.video_id,
    t,
  ]);

  return (
    <div
      ref={playerRootRef}
      className="aspect-video w-full bg-black"
      title={t("YouTube learning video")}
    />
  );
}

function InvidiousPlayer({
  playback,
  onController,
  onTime,
  onPersist,
  onError,
  transcriptLanguage,
}: WatchingPlayerProps & {
  playback: Extract<VideoPlayback, { kind: "html5" }>;
}) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const controller = html5PlayerController(video);
    onController(controller);
    const report = () =>
      onTime(controller.currentTime(), controller.duration());
    const ready = () => {
      if (playback.start_seconds > 0) controller.seek(playback.start_seconds);
      report();
    };
    video.addEventListener("loadedmetadata", ready);
    video.addEventListener("timeupdate", report);
    video.addEventListener("pause", onPersist);
    video.addEventListener("ended", onPersist);
    return () => {
      video.removeEventListener("loadedmetadata", ready);
      video.removeEventListener("timeupdate", report);
      video.removeEventListener("pause", onPersist);
      video.removeEventListener("ended", onPersist);
      onController(null);
      controller.destroy();
    };
  }, [onController, onPersist, onTime, playback.start_seconds]);

  return (
    <video
      ref={videoRef}
      controls
      playsInline
      className="aspect-video w-full bg-black"
      src={apiUrl(playback.stream_url)}
      onError={() =>
        onError(t("The configured Invidious stream could not be played."))
      }
    >
      <track
        kind="subtitles"
        srcLang={transcriptLanguage}
        src={apiUrl(playback.subtitles_url)}
        default
      />
    </video>
  );
}
