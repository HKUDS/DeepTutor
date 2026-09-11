"use client";

import {
  Captions,
  ChevronDown,
  ChevronUp,
  ChevronsDown,
  ExternalLink,
  FileAudio,
  Maximize2,
  Minimize2,
  Pencil,
  Search,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";
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
import { useReading } from "@/context/ReadingContext";
import type { AnnotationItem } from "@/lib/reading-api";
import {
  bilibiliOfficialUrl,
  parseBilibiliSource,
  youtubeEntryTime,
  youtubeVideoId,
} from "@/lib/reading-video-sources";
import { type ReadingLibraryMaterial } from "@/lib/reading-workspace-api";
import {
  stepTranscriptMatch,
  transcriptMatchIndexes,
} from "@/lib/transcript-search";
import { transcriptFollowScrollTop } from "@/lib/transcript-follow";
import { YouTubeReadingPlayer } from "./YouTubeReadingPlayer";
import { BilibiliReadingPlayer } from "./BilibiliReadingPlayer";
import { formatMediaTime, timeFromSourceHref } from "@/lib/reading-media-time";
import type { TranscriptRow } from "./types";

export function MediaReadingStage({
  material,
  title,
  refs,
  transcript,
  transcriptUnavailable,
  chaptersOnly,
  activeLocator,
  onLocatorChange,
}: {
  material: ReadingLibraryMaterial;
  title: string;
  refs: UnitReference[];
  transcript: TranscriptRow[];
  transcriptUnavailable: boolean;
  chaptersOnly: boolean;
  activeLocator: number;
  onLocatorChange: (locator: number) => void;
}) {
  const { t } = useTranslation();
  const { annotations, saveMark, removeMark } = useReading();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const controllerRef = useRef<ReadingMediaController | null>(null);
  const mediaStageRef = useRef<HTMLDivElement | null>(null);
  const transcriptListRef = useRef<HTMLDivElement | null>(null);
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
  const [followTranscript, setFollowTranscript] = useState(true);
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [selectedTranscriptMatch, setSelectedTranscriptMatch] = useState(-1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [editingNoteId, setEditingNoteId] = useState("");
  const [noteEditorOpen, setNoteEditorOpen] = useState(false);
  const activeRef = refs.find((row) => row.locator === activeLocator);
  const normalizedTranscriptQuery = transcriptQuery.trim();
  const transcriptMatches = useMemo(
    () => transcriptMatchIndexes(transcript, normalizedTranscriptQuery),
    [transcript, normalizedTranscriptQuery],
  );
  const activeTranscriptIndex = transcript.findIndex(
    (row) => row.locator === activeLocator,
  );
  const activeCue = activeTranscriptIndex >= 0 ? transcript[activeTranscriptIndex] : null;
  const activeNotes = annotations.filter(
    (row) => row.locator === activeLocator && row.kind === "note",
  );
  const nextCue =
    activeTranscriptIndex >= 0 ? transcript[activeTranscriptIndex + 1] : null;
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

  useEffect(() => {
    const onFullscreenChange = () =>
      setIsFullscreen(document.fullscreenElement === mediaStageRef.current);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const node = mediaStageRef.current;
    if (!node) return;
    if (document.fullscreenElement === node) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    const request = node.requestFullscreen();
    if (request) {
      request.catch(() =>
        setPlayerError(t("Fullscreen is unavailable for this player.")),
      );
    }
  }, [t]);

  const startNote = useCallback(() => {
    setEditingNoteId("");
    setNoteDraft("");
    setNoteEditorOpen(true);
  }, []);

  const editNote = useCallback((annotation: AnnotationItem) => {
    setEditingNoteId(annotation.annotation_id);
    setNoteDraft(annotation.note);
    setNoteEditorOpen(true);
  }, []);

  const saveNote = useCallback(() => {
    if (!activeCue) return;
    const body = noteDraft.trim();
    if (!body) return;
    const editing = activeNotes.find(
      (row) => row.annotation_id === editingNoteId,
    );
    const seconds = Math.floor(
      timeFromSourceHref(activeCue.sourceHref) ?? time,
    );
    const now = Date.now() / 1000;
    const optimistic: AnnotationItem = {
      annotation_id: editing?.annotation_id || `pending-${Date.now()}`,
      locator: activeCue.locator,
      material_revision: editing?.material_revision ?? 1,
      kind: "note",
      color: editing?.color || "yellow",
      quote: activeCue.text,
      note: body,
      rects: [],
      source_anchor: `#t=${seconds}`,
      selectors: [],
      author: editing?.author || "user",
      created_at: editing?.created_at || now,
      updated_at: now,
    };
    void saveMark(
      {
        annotation_id: editing?.annotation_id,
        locator: activeCue.locator,
        kind: "note",
        quote: activeCue.text,
        note: body,
        source_anchor: `#t=${seconds}`,
      },
      optimistic,
    ).then(() => {
      setNoteDraft("");
      setEditingNoteId("");
      setNoteEditorOpen(false);
    });
  }, [activeCue, activeNotes, editingNoteId, noteDraft, saveMark, time]);

  const selectCue = useCallback(
    (row: TranscriptRow) => {
      const seconds = timeFromSourceHref(row.sourceHref);
      if (seconds !== null) {
        controllerRef.current?.seek(seconds);
        setReadingViewport({ locator: row.locator, timeSeconds: seconds });
      }
      onLocatorChangeRef.current(row.locator);
    },
    [],
  );

  const moveTranscriptMatch = useCallback(
    (direction: 1 | -1) => {
      if (!transcriptMatches.length) return;
      const next = stepTranscriptMatch(
        selectedTranscriptMatch,
        transcriptMatches.length,
        direction,
      );
      const row = transcript[transcriptMatches[next]];
      if (!row) return;
      setFollowTranscript(false);
      setSelectedTranscriptMatch(next);
      selectCue(row);
      window.requestAnimationFrame(() => {
        transcriptListRef.current
          ?.querySelector<HTMLElement>(`[data-transcript-cue="${transcriptMatches[next]}"]`)
          ?.scrollIntoView({ block: "center" });
      });
    },
    [selectCue, selectedTranscriptMatch, transcript, transcriptMatches],
  );

  useEffect(() => {
    if (!followTranscript || !activeCue) return;
    const list = transcriptListRef.current;
    const activeRow = list?.querySelector<HTMLButtonElement>(
      '[data-active-cue="true"]',
    );
    if (!list || !activeRow) return;
    const targetTop = transcriptFollowScrollTop({
      rowOffset:
        activeRow.getBoundingClientRect().top -
        list.getBoundingClientRect().top +
        list.scrollTop,
      rowHeight: activeRow.clientHeight,
      viewportHeight: list.clientHeight,
      contentHeight: list.scrollHeight,
      currentScrollTop: list.scrollTop,
    });
    if (Math.abs(targetTop - list.scrollTop) < 1) return;
    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    list.scrollTo({
      top: targetTop,
      behavior: prefersReducedMotion ? "instant" : "smooth",
    });
  }, [activeCue, followTranscript]);

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
  const visibleTranscriptIndexes = normalizedTranscriptQuery
    ? transcriptMatches
    : transcript.map((_, index) => index);

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
          <button
            type="button"
            onClick={toggleFullscreen}
            aria-label={
              isFullscreen ? t("Exit fullscreen") : t("Enter fullscreen")
            }
            aria-pressed={isFullscreen}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--primary)]"
          >
            {isFullscreen ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
          </button>
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
          <div
            ref={mediaStageRef}
            data-fullscreen={isFullscreen || undefined}
            className={`relative flex flex-col gap-3 ${
              isFullscreen
                ? "min-h-0 flex-1 bg-black p-3 sm:p-5"
                : ""
            }`}
          >
            {isFullscreen && (
              <button
                type="button"
                onClick={toggleFullscreen}
                aria-label={t("Exit fullscreen")}
                className="absolute right-3 top-3 z-10 rounded-md bg-black/60 p-2 text-white hover:bg-black/80"
              >
                <Minimize2 size={13} />
              </button>
            )}
            {material.source_kind === "youtube" && youtubeId ? (
              <div
                className={`relative aspect-video w-full overflow-hidden bg-black shadow-[0_18px_50px_rgba(0,0,0,.18)] ${
                  isFullscreen
                    ? "mx-auto max-h-[calc(100vh-136px)] max-w-full rounded-lg"
                    : "rounded-2xl"
                }`}
              >
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
              <div
                className={`relative aspect-video w-full overflow-hidden bg-black shadow-[0_18px_50px_rgba(0,0,0,.18)] ${
                  isFullscreen
                    ? "mx-auto max-h-[calc(100vh-136px)] max-w-full rounded-lg"
                    : "rounded-2xl"
                }`}
              >
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
                className={`aspect-video w-full bg-black object-contain shadow-[0_18px_50px_rgba(0,0,0,.18)] ${
                  isFullscreen ? "rounded-lg" : "rounded-2xl"
                }`}
              />
            )}

            <div
              aria-live="polite"
              className="grid shrink-0 grid-cols-1 gap-1 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[11.5px] leading-[1.55] dark:border-[var(--border)] dark:bg-[var(--card)]"
            >
              {[activeCue, nextCue].map((row, index) =>
                row ? (
                  <button
                    key={`${row.locator}-${index}`}
                    type="button"
                    data-testid={`media-caption-${index === 0 ? "current" : "next"}`}
                    onClick={() => selectCue(row)}
                    className={`flex min-w-0 items-baseline gap-2 rounded-md px-1 py-0.5 text-left ${
                      index === 0
                        ? "font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                    }`}
                  >
                    <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]">
                      {formatMediaTime(
                        timeFromSourceHref(row.sourceHref) || 0,
                      )}
                    </span>
                    <span className="line-clamp-1 min-w-0">{row.text}</span>
                  </button>
                ) : index === 0 ? (
                  <p key="caption-current-empty" className="truncate px-1 py-0.5 text-[var(--muted-foreground)]">
                    {transcriptUnavailable ? t("No transcript available") : t("Beginning")}
                  </p>
                ) : null,
              )}
            </div>
          </div>

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
                onClick={startNote}
                disabled={!activeCue}
                aria-label={t("Add segment note")}
                title={t("Add segment note")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--primary)] disabled:opacity-40"
              >
                <StickyNote size={12} />
              </button>
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

          <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--card)] dark:border-[var(--border)] dark:bg-[var(--card)]">
            {noteEditorOpen && (
              <div className="border-b border-[var(--border)] p-3 dark:border-[var(--border)]">
                <label className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
                  {editingNoteId ? t("Edit note") : t("New note")}
                </label>
                <textarea
                  value={noteDraft}
                  data-testid="media-note-input"
                  onChange={(event) => setNoteDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setNoteDraft("");
                      setEditingNoteId("");
                      setNoteEditorOpen(false);
                    }
                  }}
                  rows={3}
                  className="mt-2 w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-[11.5px] leading-relaxed outline-none focus:border-[var(--primary)]"
                />
                <div className="mt-2 flex justify-end gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setNoteDraft("");
                      setEditingNoteId("");
                    }}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                  >
                    <X size={11} />
                    {t("Cancel")}
                  </button>
                  <button
                    type="button"
                    onClick={saveNote}
                    disabled={!noteDraft.trim()}
                    data-testid="media-note-save"
                    className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-2 py-1 text-[10.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
                  >
                    <StickyNote size={11} />
                    {t("Save note")}
                  </button>
                </div>
              </div>
            )}
            {activeNotes.length ? (
              <ul className="divide-y divide-[var(--border)] dark:divide-[var(--border)]">
                {activeNotes.map((annotation) => (
                  <li
                    key={annotation.annotation_id}
                    className="flex items-start gap-3 px-3 py-2"
                  >
                    <StickyNote
                      size={12}
                      className="mt-0.5 shrink-0 text-[var(--primary)]"
                    />
                    <div className="min-w-0 flex-1">
                      <p
                        data-testid="media-note-body"
                        className="text-[11.5px] leading-relaxed"
                      >
                        {annotation.note}
                      </p>
                      <p className="mt-1 line-clamp-2 text-[10px] text-[var(--muted-foreground)]">
                        {annotation.quote}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => editNote(annotation)}
                        aria-label={t("Edit note")}
                        title={t("Edit note")}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--primary)]"
                      >
                        <Pencil size={11} />
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeMark(annotation)}
                        aria-label={t("Delete note")}
                        title={t("Delete note")}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--destructive)]"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
                !noteEditorOpen && (
                <button
                  type="button"
                  onClick={startNote}
                  disabled={!activeCue}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  <StickyNote size={12} />
                  {t("Add a note for this segment")}
                </button>
              )
            )}
          </div>

          <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] dark:border-[var(--border)] dark:bg-[var(--card)]">
            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-3 py-2 dark:border-[var(--border)]">
              <label className="relative min-w-[180px] flex-1">
                <span className="sr-only">{t("Search transcript")}</span>
                <Search
                  size={11}
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
                />
                <input
                  type="search"
                  value={transcriptQuery}
                  aria-label={t("Search transcript")}
                  placeholder={t("Search transcript")}
                  onChange={(event) => {
                    const next = event.target.value;
                    setTranscriptQuery(next);
                    setSelectedTranscriptMatch(-1);
                    if (next.trim()) setFollowTranscript(false);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setTranscriptQuery("");
                      setSelectedTranscriptMatch(-1);
                      return;
                    }
                    if (event.key === "Enter") {
                      event.preventDefault();
                      moveTranscriptMatch(event.shiftKey ? -1 : 1);
                    }
                  }}
                  className="h-8 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] pl-8 pr-2 text-[10.5px] outline-none"
                />
              </label>
              {!!normalizedTranscriptQuery && (
                <span
                  aria-live="polite"
                  className="text-[10px] tabular-nums text-[var(--muted-foreground)]"
                >
                  {t("{{count}} transcript matches", {
                    count: transcriptMatches.length,
                  })}
                </span>
              )}
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={!transcriptMatches.length}
                  aria-label={t("Previous transcript match")}
                  onClick={() => moveTranscriptMatch(-1)}
                  className="rounded-md border border-[var(--border)] p-1.5 text-[var(--muted-foreground)] disabled:opacity-40"
                >
                  <ChevronUp size={11} />
                </button>
                <button
                  type="button"
                  disabled={!transcriptMatches.length}
                  aria-label={t("Next transcript match")}
                  onClick={() => moveTranscriptMatch(1)}
                  className="rounded-md border border-[var(--border)] p-1.5 text-[var(--muted-foreground)] disabled:opacity-40"
                >
                  <ChevronDown size={11} />
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setFollowTranscript((current) => !current)
                  }
                  disabled={Boolean(normalizedTranscriptQuery)}
                  aria-pressed={followTranscript}
                  className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1.5 text-[10px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
                    followTranscript
                      ? "border-[var(--primary)] text-[var(--primary)]"
                      : "border-[var(--border)] text-[var(--muted-foreground)]"
                  }`}
                >
                  <ChevronsDown size={11} />
                  {t("Follow playback")}
                </button>
              </div>
            </div>
            <div
              ref={transcriptListRef}
              data-testid="reading-media-transcript-list"
              className="max-h-[min(48vh,460px)] min-h-[180px] overflow-y-auto p-2"
              onWheel={() => setFollowTranscript(false)}
              onTouchMove={() => setFollowTranscript(false)}
              onPointerDown={(event) => {
                if (event.target === event.currentTarget)
                  setFollowTranscript(false);
              }}
              onKeyDown={(event) => {
                if (
                  ["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"].includes(
                    event.key,
                  )
                )
                  setFollowTranscript(false);
              }}
            >
              {transcriptUnavailable ? (
                <p className="p-3 text-[10.5px] text-[var(--muted-foreground)]">
                  {chaptersOnly
                    ? t("Only chapter markers are available for this video.")
                    : t("No transcript cues available.")}
                </p>
              ) : normalizedTranscriptQuery && transcriptMatches.length === 0 ? (
                <p className="p-3 text-[10.5px] text-[var(--muted-foreground)]">
                  {t("No transcript matches.")}
                </p>
              ) : transcript.length === 0 ? (
                <p className="p-3 text-[10.5px] text-[var(--muted-foreground)]">
                  {t("No transcript cues available.")}
                </p>
              ) : (
                <div className="space-y-0.5">
                  {visibleTranscriptIndexes.map((index) => {
                    const row = transcript[index];
                    const active = row.locator === activeLocator;
                    const selectedMatch =
                      Boolean(normalizedTranscriptQuery) &&
                      transcriptMatches[selectedTranscriptMatch] === index;
                    return (
                      <button
                        key={`${row.locator}-${row.sourceHref}`}
                        type="button"
                        data-active-cue={active ? "true" : undefined}
                        data-transcript-cue={index}
                        onClick={() => {
                          setFollowTranscript(false);
                          selectCue(row);
                        }}
                        className={`flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-[10.5px] ${
                          active
                            ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]"
                            : selectedMatch
                              ? "bg-[color-mix(in_srgb,var(--primary)_7%,transparent)] text-[var(--foreground)]"
                              : "text-[var(--foreground)] hover:bg-[var(--muted)]"
                        }`}
                      >
                        <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]">
                          {row.title}
                        </span>
                        <span className="line-clamp-2 min-w-0 leading-[1.5]">
                          {row.text}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
