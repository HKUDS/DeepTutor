"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiUrl } from "@/lib/api";
import {
  DEFAULT_PLAYBACK_RATE,
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
  if (props.playback.kind === "bilibili_iframe") {
    return <BilibiliPlayer {...props} playback={props.playback} />;
  }
  return props.playback.kind === "youtube_iframe" ? (
    <YouTubePlayer {...props} playback={props.playback} />
  ) : (
    <InvidiousPlayer {...props} playback={props.playback} />
  );
}

/** Bilibili embed: the official external player has no JS API — we can start
 *  at a timestamp (remount on seek) but cannot track live position. Same
 *  honest contract as BilibiliReadingPlayer in the reading workspace. */
function BilibiliPlayer({
  playback,
  onController,
  onTime,
}: WatchingPlayerProps & {
  playback: Extract<VideoPlayback, { kind: "bilibili_iframe" }>;
}) {
  const { t } = useTranslation();
  const [start, setStart] = useState(playback.start_seconds);
  const timeRef = useRef(playback.start_seconds);
  const controller = useMemo(
    () => ({
      currentTime: () => timeRef.current,
      duration: () => Number.POSITIVE_INFINITY,
      playbackRate: () => DEFAULT_PLAYBACK_RATE,
      seek: (seconds: number) => {
        const next = Math.max(0, seconds);
        timeRef.current = next;
        setStart(next);
        onTime(next, Number.POSITIVE_INFINITY);
      },
      setPlaybackRate: () => undefined,
      play: () => undefined,
      pause: () => undefined,
      destroy: () => undefined,
      tracksPosition: false,
    }),
    [onTime],
  );
  useEffect(() => {
    onController(controller);
    onTime(timeRef.current, Number.POSITIVE_INFINITY);
    return () => onController(null);
  }, [controller, onController, onTime]);
  return (
    <div className="relative h-full w-full">
      <iframe
        src={`https://player.bilibili.com/player.html?bvid=${playback.bvid}&page=${playback.page}&autoplay=0&start=${Math.floor(start)}`}
        title="Bilibili"
        className="aspect-video h-full w-full border-0 bg-black"
        allow="autoplay; fullscreen; picture-in-picture"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
      <div className="pointer-events-none absolute right-2 bottom-2 rounded bg-slate-900/70 px-2 py-1 text-xs text-slate-200">
        {t("Bilibili 播放器不支持进度跟随；答疑不受影响。")}
      </div>
    </div>
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
