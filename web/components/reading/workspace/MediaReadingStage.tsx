"use client";

import { ExternalLink, FileAudio } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  type UnitReference,
  getReadingPosition,
  rawMaterialUrl,
  saveReadingPosition,
} from "@/lib/reading-api";
import {
  type ReadingMediaController,
  html5ReadingController,
} from "@/lib/reading-media-controller";
import { mediaTimeFromHref } from "@/lib/reading-media-citations";
import {
  READER_ACTION_EVENT,
  READER_TURN_END_EVENT,
  type ReaderActionPayload,
} from "@/lib/reading-reader-action";
import { setReadingViewport } from "@/lib/reading-turn-state";
import {
  bilibiliOfficialUrl,
  parseBilibiliSource,
  youtubeEntryTime,
  youtubeVideoId,
} from "@/lib/reading-video-sources";
import { type ReadingLibraryMaterial } from "@/lib/reading-workspace-api";
import { YouTubeReadingPlayer } from "./YouTubeReadingPlayer";
import { BilibiliReadingPlayer } from "./BilibiliReadingPlayer";
import { timeFromSourceHref } from "@/lib/reading-media-time";

export function MediaReadingStage({
  material,
  title,
  refs,
  transcriptUnavailable,
  chaptersOnly,
  activeLocator,
  onLocatorChange,
}: {
  material: ReadingLibraryMaterial;
  title: string;
  refs: UnitReference[];
  transcriptUnavailable: boolean;
  chaptersOnly: boolean;
  activeLocator: number;
  onLocatorChange: (locator: number) => void;
}) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const controllerRef = useRef<ReadingMediaController | null>(null);
  const onLocatorChangeRef = useRef(onLocatorChange);
  const activeLocatorRef = useRef(activeLocator);
  const playbackLocatorRef = useRef(0);
  const stateRef = useRef({ time: 0, duration: 0 });
  const lastSavedRef = useRef(0);
  const youtubeId = youtubeVideoId(material.source_url);
  const bilibiliSource = useMemo(
    () => parseBilibiliSource(material.source_url),
    [material.source_url],
  );
  const sourceEntryTime =
    material.source_kind === "bilibili"
      ? bilibiliSource?.startSeconds || 0
      : youtubeEntryTime(material.source_url);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(material.duration_seconds || 0);
  const [startSeconds, setStartSeconds] = useState(sourceEntryTime);
  const [playerError, setPlayerError] = useState("");
  const activeRef = refs.find((row) => row.locator === activeLocator);
  const timedRefs = useMemo(
    () =>
      refs
        .map((row) => ({ ...row, time: timeFromSourceHref(row.source_href) }))
        .filter((row) => row.time !== null)
        .sort((left, right) => Number(left.time) - Number(right.time)),
    [refs],
  );

  useEffect(() => {
    onLocatorChangeRef.current = onLocatorChange;
  }, [onLocatorChange]);

  const notifyLocator = useCallback((locator: number) => {
    onLocatorChangeRef.current(locator);
  }, []);

  useEffect(() => {
    activeLocatorRef.current = activeLocator;
  }, [activeLocator]);

  const locatorAtTime = useCallback(
    (seconds: number) => {
      let locator = timedRefs[0]?.locator ?? 1;
      for (const row of timedRefs) {
        if (Number(row.time) > seconds + 0.05) break;
        locator = row.locator;
      }
      return locator;
    },
    [timedRefs],
  );

  const persist = useCallback(() => {
    const current = stateRef.current;
    if (current.time < 0 || !refs.length) return;
    const locator = Math.max(
      1,
      activeLocatorRef.current || locatorAtTime(current.time),
    );
    void saveReadingPosition(material.material_id, {
      locator,
      source_anchor: `#t=${Math.floor(current.time)}`,
      percentage:
        current.duration > 0
          ? Math.min(1, Math.max(0, current.time / current.duration))
          : 0,
    }).catch(() => undefined);
    lastSavedRef.current = current.time;
  }, [locatorAtTime, material.material_id, refs.length]);

  const handleTime = useCallback(
    (nextTime: number, nextDuration: number) => {
      stateRef.current = { time: nextTime, duration: nextDuration };
      setTime(nextTime);
      setDuration(nextDuration);
      setReadingViewport({ timeSeconds: nextTime });
      const locator = locatorAtTime(nextTime);
      if (locator && locator !== activeLocatorRef.current) {
        playbackLocatorRef.current = locator;
        activeLocatorRef.current = locator;
        notifyLocator(locator);
      }
      if (Math.abs(nextTime - lastSavedRef.current) >= 5) persist();
    },
    [locatorAtTime, notifyLocator, persist],
  );

  const [untrackedPlayback, setUntrackedPlayback] = useState(false);

  const handleController = useCallback(
    (controller: ReadingMediaController | null) => {
      controllerRef.current = controller;
      setUntrackedPlayback(controller ? !controller.tracksPosition : false);
    },
    [],
  );

  const handlePlayerError = useCallback(
    (error: number | string) => {
      if (error === 101 || error === 150) {
        setPlayerError(
          t(
            "This video's owner disabled embedded playback. Open it on YouTube; DeepTutor can still use captions when they are available.",
          ),
        );
      } else if (error === 153) {
        setPlayerError(
          t(
            "YouTube could not verify this embedded player. Open the official video, or check the browser's referrer policy.",
          ),
        );
      } else if (typeof error === "number") {
        setPlayerError(
          t("YouTube playback failed ({{code}}).", { code: error }),
        );
      } else {
        setPlayerError(error);
      }
    },
    [t],
  );

  // A container the browser cannot decode (Matroska is the common one) shows
  // as an inert black rectangle otherwise. Say so, and offer the file itself —
  // the transcript and the companion are unaffected either way.
  const handleUnplayable = useCallback(() => {
    setPlayerError(
      t(
        "Your browser cannot play this file's format. The transcript and the companion still work — open the original to watch it elsewhere.",
      ),
    );
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    void getReadingPosition(material.material_id)
      .then((position) => {
        if (cancelled) return;
        const savedTime = timeFromSourceHref(position.source_anchor);
        const entry =
          material.source_kind === "bilibili"
            ? parseBilibiliSource(material.source_url)?.startSeconds || 0
            : youtubeEntryTime(material.source_url);
        const nextStart = savedTime ?? entry;
        setStartSeconds(nextStart);
        if (
          position.locator > 0 &&
          refs.some((row) => row.locator === position.locator)
        ) {
          activeLocatorRef.current = position.locator;
          notifyLocator(position.locator);
        }
        controllerRef.current?.seek(nextStart);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [
    material.material_id,
    material.source_kind,
    material.source_url,
    notifyLocator,
    refs,
  ]);

  useEffect(() => {
    if (
      material.source_kind === "youtube" ||
      material.source_kind === "bilibili"
    )
      return;
    const node =
      material.render_mode === "audio" ? audioRef.current : videoRef.current;
    if (!node) return;
    const controller = html5ReadingController(node);
    controllerRef.current = controller;
    const report = () =>
      handleTime(controller.currentTime(), controller.duration());
    const ready = () => {
      if (startSeconds > 0) controller.seek(startSeconds);
      report();
    };
    node.addEventListener("loadedmetadata", ready);
    node.addEventListener("timeupdate", report);
    node.addEventListener("pause", persist);
    node.addEventListener("ended", persist);
    return () => {
      node.removeEventListener("loadedmetadata", ready);
      node.removeEventListener("timeupdate", report);
      node.removeEventListener("pause", persist);
      node.removeEventListener("ended", persist);
      if (controllerRef.current === controller) controllerRef.current = null;
      controller.destroy();
    };
  }, [
    handleTime,
    material.render_mode,
    material.source_kind,
    persist,
    startSeconds,
  ]);

  useEffect(() => {
    if (playbackLocatorRef.current === activeLocator) {
      playbackLocatorRef.current = 0;
      return;
    }
    const target = timedRefs.find((row) => row.locator === activeLocator);
    if (target?.time !== null && target?.time !== undefined) {
      controllerRef.current?.seek(Number(target.time));
      setReadingViewport({
        locator: activeLocator,
        timeSeconds: Number(target.time),
      });
    }
  }, [activeLocator, timedRefs]);

  useEffect(() => {
    const onReaderAction = (event: Event) => {
      const detail = (event as CustomEvent<ReaderActionPayload>).detail;
      if (!detail || detail.material_id !== material.material_id) return;
      const locator = Number(detail.locator || 0);
      if (locator >= 1) notifyLocator(locator);
    };
    window.addEventListener(READER_ACTION_EVENT, onReaderAction);
    return () =>
      window.removeEventListener(READER_ACTION_EVENT, onReaderAction);
  }, [material.material_id, notifyLocator]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const anchor = (event.target as HTMLElement | null)?.closest?.(
        "a[href]",
      ) as HTMLAnchorElement | null;
      const seconds = mediaTimeFromHref(anchor?.getAttribute("href"));
      if (seconds === null) return;
      event.preventDefault();
      event.stopPropagation();
      controllerRef.current?.seek(seconds);
      const locator = locatorAtTime(seconds);
      if (locator) notifyLocator(locator);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [locatorAtTime, notifyLocator]);

  useEffect(() => {
    const onTurnEnd = (event: Event) => {
      if ((event as CustomEvent<{ moved?: boolean }>).detail?.moved) return;
      window.setTimeout(() => {
        const answers = document.querySelectorAll('[role="article"]');
        const anchor = answers[
          answers.length - 1
        ]?.querySelector<HTMLAnchorElement>('a[href^="#dt-media-time-"]');
        const seconds = mediaTimeFromHref(anchor?.getAttribute("href"));
        if (seconds === null) return;
        controllerRef.current?.seek(seconds);
        notifyLocator(locatorAtTime(seconds));
      }, 120);
    };
    window.addEventListener(READER_TURN_END_EVENT, onTurnEnd);
    return () => window.removeEventListener(READER_TURN_END_EVENT, onTurnEnd);
  }, [locatorAtTime, notifyLocator]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") persist();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      persist();
      setReadingViewport({ timeSeconds: null });
    };
  }, [persist]);

  const lastReferenceTime = timedRefs.length
    ? Number(timedRefs[timedRefs.length - 1].time || 0)
    : 0;
  const timelineDuration = Math.max(
    duration,
    material.duration_seconds || 0,
    lastReferenceTime,
  );
  const officialUrl = youtubeId
    ? `https://youtu.be/${youtubeId}?t=${Math.floor(time)}`
    : bilibiliSource
      ? bilibiliOfficialUrl(bilibiliSource, time)
      : "";
  const provider =
    material.source_kind === "youtube"
      ? "YouTube"
      : material.source_kind === "bilibili"
        ? "Bilibili"
        : t("Native media");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--background)] px-3 dark:border-[var(--border)] dark:bg-[var(--background)]">
        <div className="min-w-0">
          <p className="truncate text-[10.5px] font-semibold">{title}</p>
          <p className="truncate text-[10.5px] text-[var(--muted-foreground)]">
            {provider} · {activeRef?.title || t("Transcript")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {officialUrl && (
            <a
              href={officialUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[10px] text-[var(--primary)] hover:underline"
            >
              {t("Open official")}
              <ExternalLink size={9} />
            </a>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5 lg:p-7">
        <div className="mx-auto flex h-full max-w-[980px] flex-col">
          {material.source_kind === "youtube" && youtubeId ? (
            <div className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black shadow-[0_18px_50px_rgba(0,0,0,.18)]">
              <YouTubeReadingPlayer
                videoId={youtubeId}
                startSeconds={startSeconds}
                title={title}
                onController={handleController}
                onTime={handleTime}
                onPersist={persist}
                onError={handlePlayerError}
              />
            </div>
          ) : material.source_kind === "bilibili" && bilibiliSource ? (
            <div className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black shadow-[0_18px_50px_rgba(0,0,0,.18)]">
              <BilibiliReadingPlayer
                key={`${material.material_id}-${Math.floor(startSeconds)}`}
                source={bilibiliSource}
                startSeconds={startSeconds}
                duration={timelineDuration}
                title={title}
                onController={handleController}
                onTime={handleTime}
                onError={handlePlayerError}
              />
            </div>
          ) : material.render_mode === "audio" ? (
            <div className="flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] p-8 shadow-[0_18px_50px_rgba(0,0,0,.08)] dark:border-[var(--border)] dark:bg-[var(--card)]">
              <span className="mb-5 flex size-20 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--primary)]">
                <FileAudio size={30} />
              </span>
              <p className="mb-5 max-w-md text-center font-serif text-[20px] font-medium">
                {title}
              </p>
              <audio
                ref={audioRef}
                controls
                preload="metadata"
                src={rawMaterialUrl(material.material_id)}
                onError={handleUnplayable}
                className="w-full max-w-xl"
              />
            </div>
          ) : (
            <video
              ref={videoRef}
              controls
              preload="metadata"
              poster={material.cover_url || undefined}
              src={rawMaterialUrl(material.material_id)}
              onError={handleUnplayable}
              className="aspect-video w-full rounded-2xl bg-black object-contain shadow-[0_18px_50px_rgba(0,0,0,.18)]"
            />
          )}

          {(playerError || transcriptUnavailable) && (
            <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-[10.5px] leading-relaxed text-[var(--muted-foreground)] dark:border-[var(--border)] dark:bg-[var(--card)]">
              {playerError ||
                (chaptersOnly
                  ? t(
                      "Only chapter markers are available for this video. You can navigate by chapter, but the companion will not treat them as a spoken transcript.",
                    )
                  : t(
                      "This video has no accessible transcript. Playback works, but the companion cannot ground explanations in its spoken content.",
                    ))}
              {playerError && !officialUrl && (
                <a
                  href={rawMaterialUrl(material.material_id)}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 inline-flex items-center gap-1 text-[var(--primary)] hover:underline"
                >
                  {t("Open the original file")}
                  <ExternalLink size={9} />
                </a>
              )}
            </div>
          )}

          <div className="mt-4 flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 dark:border-[var(--border)] dark:bg-[var(--card)]">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--primary)]">
                {t("Current passage")}
              </p>
              <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)] dark:text-[var(--foreground)]">
                {activeRef?.title || t("Beginning")}
              </p>
              {/* Say it once, here, where the claim is made. A player that
                  cannot report its position leaves this label frozen, which
                  reads as a broken feature rather than a platform limit. */}
              {untrackedPlayback && (
                <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
                  {t(
                    "This player does not report playback position, so the passage follows the controls below rather than the video.",
                  )}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onLocatorChange(Math.max(1, activeLocator - 1))}
                disabled={activeLocator <= 1}
                className="rounded-lg px-2 py-1 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
              >
                {t("Previous")}
              </button>
              <button
                type="button"
                onClick={() =>
                  onLocatorChange(Math.min(refs.length, activeLocator + 1))
                }
                disabled={activeLocator >= refs.length}
                className="rounded-lg px-2 py-1 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
              >
                {t("Next")}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
