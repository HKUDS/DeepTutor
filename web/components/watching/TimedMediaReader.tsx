"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  BookmarkPlus,
  Compass,
  ExternalLink,
  FilePlus2,
  Flag,
  Globe,
  Loader2,
  Maximize2,
  MessageSquareText,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  PictureInPicture2,
  Plus,
  Sparkles,
  StickyNote,
  Upload,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import {
  addVideoNote,
  createBookFromVideo,
  createTranscriptJob,
  createVideoMark,
  connectYouTubeSession,
  deleteVideoMark,
  getInvidiousStatus,
  getVideoLearningMaterial,
  getTranscriptJob,
  patchVideoMark,
  publishVideoToKb,
  recordWatchProgress,
  requestSubtitlePrefetch,
  suggestVideoMarks,
  timedMediaStreamUrl,
  timedMediaSubtitleUrl,
  type VideoLearningMark,
  type VideoMarkKind,
  type VideoMarkSuggestion,
} from "@/lib/video-learning-api";
import {
  VIDEO_MARK_COLORS,
  cueIndexesFromSelection,
  findActiveCueIndex,
  formatWatchTime,
  locatorsForRange,
  noteMatchesCue,
  rangeFromCues,
} from "@/lib/video-learning-marks";
import { WATCHING_ASK_EVENT } from "@/lib/watching-turn-state";
import { InvidiousHome } from "./InvidiousHome";
import {
  createRendererLaunch,
} from "@/lib/video-learning-remote-api";
import { invidiousFallbackUrl, shouldOpenInvidiousInCurrentTab } from "@/lib/invidious-open";
import { KeyPointsPanel } from "./KeyPointsPanel";
import { LearningTimeline } from "./LearningTimeline";

type WatchTab = "transcript" | "notes" | "marks";

type WebKitVideoElement = HTMLVideoElement & {
  webkitPresentationMode?: string;
  webkitSetPresentationMode?: (mode: "inline" | "fullscreen" | "picture-in-picture") => void;
};

function showVideoCaptions(video: HTMLVideoElement | null) {
  if (!video) return;
  for (let index = 0; index < video.textTracks.length; index += 1) {
    video.textTracks[index].mode = "showing";
  }
}

export function TimedMediaReader({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const {
    material,
    currentTime,
    pendingSeek,
    openUrl,
    replaceMaterial,
    close,
    setCurrentTime,
    seek,
    clearSeek,
  } = useWatching();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const readerRef = useRef<HTMLElement | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const actionBarRef = useRef<HTMLDivElement | null>(null);
  const insideMarksRef = useRef<Set<string>>(new Set());
  const [showInvidiousHome, setShowInvidiousHome] = useState(false);
  const [invidiousPublicUrl, setInvidiousPublicUrl] = useState<string>("");
  const [tab, setTab] = useState<WatchTab>("transcript");
  const [jobMessage, setJobMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [youtubeConnecting, setYoutubeConnecting] = useState(false);
  const [youtubeMessage, setYoutubeMessage] = useState("");
  const [noteText, setNoteText] = useState("");
  const [noteMessage, setNoteMessage] = useState("");
  const [cueNoteDraft, setCueNoteDraft] = useState<{ cueIndex: number; timeSeconds: number; quote: string } | null>(null);
  const [cueNoteText, setCueNoteText] = useState("");
  const [cueNoteSaving, setCueNoteSaving] = useState(false);
  const [playbackErrorMaterialId, setPlaybackErrorMaterialId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ start_seconds: number; end_seconds: number; quote: string; note?: string } | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const [rangeStart, setRangeStart] = useState<number | null>(null);
  const [markError, setMarkError] = useState("");
  const [suggestions, setSuggestions] = useState<VideoMarkSuggestion[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [endPrompt, setEndPrompt] = useState<VideoLearningMark | null>(null);
  const [kbBusy, setKbBusy] = useState(false);
  const [bookBusy, setBookBusy] = useState(false);
  const [publishMessage, setPublishMessage] = useState("");
  const [rendererMessage, setRendererMessage] = useState("");
  const [openingInvidious, setOpeningInvidious] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [assistantPanelOpen, setAssistantPanelOpen] = useState(false);
  const [pipSupported, setPipSupported] = useState(false);
  const [pipActive, setPipActive] = useState(false);

  const cumulativePlayedRef = useRef<number>(0);
  const lastPlaybackTimeRef = useRef<number>(-1);
  const wasEditingTranscriptRef = useRef(false);

  useEffect(() => {
    if (!focusMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setFocusMode(false);
        setAssistantPanelOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [focusMode]);

  useEffect(() => {
    const shell = readerRef.current?.closest<HTMLElement>(".dt-reader-shell");
    if (!shell) return;
    shell.dataset.watchingFocus = focusMode ? "true" : "false";
    shell.dataset.watchingAssistant = focusMode && assistantPanelOpen ? "true" : "false";
    return () => {
      delete shell.dataset.watchingFocus;
      delete shell.dataset.watchingAssistant;
    };
  }, [assistantPanelOpen, focusMode]);

  useEffect(() => {
    const video = videoRef.current as WebKitVideoElement | null;
    if (!video) return;
    const documentWithPip = document as Document & { pictureInPictureEnabled?: boolean };
    setPipSupported(
      Boolean(
        (documentWithPip.pictureInPictureEnabled && "requestPictureInPicture" in video) ||
          video.webkitSetPresentationMode
      )
    );
    const onEnter = () => {
      showVideoCaptions(video);
      setPipActive(true);
    };
    const onLeave = () => {
      showVideoCaptions(video);
      setPipActive(false);
    };
    const onWebKitModeChange = () => {
      showVideoCaptions(video);
      setPipActive(video.webkitPresentationMode === "picture-in-picture");
    };
    video.addEventListener("enterpictureinpicture", onEnter);
    video.addEventListener("leavepictureinpicture", onLeave);
    video.addEventListener("webkitpresentationmodechanged", onWebKitModeChange);
    showVideoCaptions(video);
    return () => {
      video.removeEventListener("enterpictureinpicture", onEnter);
      video.removeEventListener("leavepictureinpicture", onLeave);
      video.removeEventListener("webkitpresentationmodechanged", onWebKitModeChange);
    };
  }, [material?.material_id]);

  useEffect(() => {
    void getInvidiousStatus()
      .then((status) => {
        if (status.invidious_public_base_url) {
          setInvidiousPublicUrl(status.invidious_public_base_url);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (material?.learning?.cumulative_played_seconds) {
      cumulativePlayedRef.current = material.learning.cumulative_played_seconds;
    } else {
      cumulativePlayedRef.current = 0;
    }
    lastPlaybackTimeRef.current = -1;
    setDraft(null);
    setCueNoteDraft(null);
    setCueNoteText("");
    setRangeStart(null);
    setSuggestions([]);
    setEndPrompt(null);
    insideMarksRef.current = new Set();
    // Reset only when switching videos; later watch-progress updates must not wipe local playback totals.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material?.material_id]);

  useEffect(() => {
    if (pendingSeek === null || !videoRef.current) return;
    videoRef.current.currentTime = pendingSeek;
    void videoRef.current.play().catch(() => {});
    clearSeek();
  }, [pendingSeek, clearSeek]);

  useEffect(() => {
    if (!material) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getVideoLearningMaterial(material.material_id);
        if (!cancelled) replaceMaterial(next);
      } catch {
        // The remote phone may be writing; the next interval will retry.
      }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [material, replaceMaterial]);

  useEffect(() => {
    if (!jobId || !material) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const job = await getTranscriptJob(jobId);
        if (cancelled) return;
        if (job.status === "completed") {
          setJobMessage(t("Subtitle generation completed."));
          setJobId(null);
          await openUrl(material.source.url);
        } else if (job.status === "failed" || job.status === "cancelled") {
          setJobMessage(job.error || t("Subtitle generation failed."));
          setJobId(null);
        } else {
          setJobMessage(`${t("Subtitle generation is running.")} ${job.progress ?? 0}%`);
        }
      } catch (caught) {
        if (!cancelled)
          setJobMessage(caught instanceof Error ? caught.message : t("Subtitle generation failed."));
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, material, openUrl, t]);

  const marks = useMemo(() => material?.learning.marks || [], [material?.learning.marks]);
  const activeCueIndex = useMemo(
    () => findActiveCueIndex(material?.transcript.cues || [], currentTime),
    [material?.transcript.cues, currentTime]
  );
  const activeCue = activeCueIndex >= 0 ? material?.transcript.cues[activeCueIndex] : undefined;
  const selectedFormat = material ? Object.keys(material.playback.formats)[0] ?? "" : "";
  const format = material?.playback.formats[selectedFormat];
  const playbackError = playbackErrorMaterialId === material?.material_id;
  const duration = material?.source.duration_seconds || material?.metadata.duration_seconds || 0;
  const editingTranscript = cueNoteDraft !== null || draft !== null;

  useEffect(() => {
    const wasEditing = wasEditingTranscriptRef.current;
    wasEditingTranscriptRef.current = editingTranscript;
    if (editingTranscript || tab !== "transcript" || activeCueIndex < 0) return;
    const frame = window.requestAnimationFrame(() => {
      const container = transcriptRef.current;
      const row = container?.querySelector<HTMLElement>(`[data-cue-index="${activeCueIndex}"]`);
      if (!container || !row) return;
      const top = row.offsetTop - (container.clientHeight - row.offsetHeight) / 2;
      container.scrollTo({ top: Math.max(0, top), behavior: wasEditing ? "auto" : "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeCueIndex, editingTranscript, tab]);

  useEffect(() => {
    if (!material) return;
    const nextInside = new Set<string>();
    for (const mark of marks) {
      if (mark.end_seconds <= mark.start_seconds) continue;
      const inside = currentTime >= mark.start_seconds && currentTime <= mark.end_seconds;
      if (inside) nextInside.add(mark.mark_id);
      else if (insideMarksRef.current.has(mark.mark_id) && currentTime > mark.end_seconds) {
        setEndPrompt(mark);
        setTab("marks");
      }
    }
    insideMarksRef.current = nextInside;
  }, [currentTime, marks, material]);

  const handleVideoSelect = async (videoUrl: string) => {
    setShowInvidiousHome(false);
    await openUrl(videoUrl);
  };

  const connectYouTubeForSubtitles = async () => {
    if (!material) return;
    setYoutubeConnecting(true);
    setYoutubeMessage(t("Using this Mac's existing Chrome session to retrieve YouTube subtitles."));
    try {
      const session = await connectYouTubeSession(material.material_id);
      if (!session.helper_available) {
        setYoutubeMessage(t("Chrome or Chromium is required on the Mac running DeepTutor."));
        return;
      }
      await requestSubtitlePrefetch(material.material_id);
      setYoutubeMessage(t("Preparing subtitles with this Mac's Chrome session."));
    } catch (caught) {
      setYoutubeMessage(caught instanceof Error ? caught.message : t("Could not connect YouTube."));
    } finally {
      setYoutubeConnecting(false);
    }
  };

  const openInvidiousRenderer = async (
    videoId?: string,
    positionSeconds?: number,
    preferSameTab = false,
  ) => {
    setOpeningInvidious(true);
    setRendererMessage(t("Opening Invidious..."));
    const fallbackUrl = invidiousFallbackUrl(invidiousPublicUrl);
    let target: Window | null = null;
    // Hub / iPad: stay in the current tab so a blocked popup cannot look like
    // "no jump". Watch page: open a tab first, then replace it with the
    // bootstrap URL after the ticket is ready.
    if (!preferSameTab) {
      target = window.open(fallbackUrl || "about:blank", "_blank");
      try {
        if (target) target.opener = null;
      } catch {
        // Some browsers expose opener as read-only for a newly opened tab.
      }
    }
    try {
      const launch = await createRendererLaunch({
        videoId,
        positionSeconds,
        materialId: material?.material_id,
      });
      try {
        const origin = new URL(launch.launch_url).origin;
        if (origin) setInvidiousPublicUrl(origin);
      } catch {
        // Keep the last known public origin if the launch URL is unexpected.
      }
      if (shouldOpenInvidiousInCurrentTab(preferSameTab, Boolean(target))) {
        window.location.assign(launch.launch_url);
        return;
      }
      if (!target) throw new Error(t("Could not open Invidious."));
      target.location.assign(launch.launch_url);
      setRendererMessage(t("Opened Invidious. Use Phone remote & notes there when ready."));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : t("Could not open Invidious.");
      if (target && fallbackUrl) {
        try {
          target.location.assign(fallbackUrl);
        } catch {
          target.close();
        }
      } else if (target) {
        target.close();
      }
      setRendererMessage(
        fallbackUrl
          ? `${message} ${t("If the page did not jump, tap Continue to Invidious.")}`
          : message,
      );
    } finally {
      setOpeningInvidious(false);
    }
  };

  if (!material || showInvidiousHome) {
    return (
      <InvidiousHome
        onSelectVideo={handleVideoSelect}
        onOpenInvidious={() => void openInvidiousRenderer(undefined, undefined, true)}
        onClose={material ? () => setShowInvidiousHome(false) : onClose}
        openingInvidious={openingInvidious}
        openMessage={rendererMessage}
        fallbackOpenUrl={invidiousFallbackUrl(invidiousPublicUrl)}
      />
    );
  }

  const currentSegment = material.segments.find((row) => currentTime >= row.start && currentTime <= row.end);
  const askAboutCurrent = (intent: "explain" | "extract" = "explain") => {
    window.dispatchEvent(
      new CustomEvent(WATCHING_ASK_EVENT, {
        detail: { timeSeconds: currentTime, text: currentSegment?.text || "", intent },
      })
    );
  };

  const syncMarks = (nextMarks: VideoLearningMark[]) => {
    replaceMaterial({
      ...material,
      learning: { ...material.learning, marks: nextMarks },
    });
  };

  const saveMark = async (payload: {
    kind: VideoMarkKind;
    start_seconds: number;
    end_seconds: number;
    quote?: string;
    note?: string;
    author?: "user" | "assistant";
  }) => {
    const locators = locatorsForRange(material.segments, payload.start_seconds, payload.end_seconds);
    try {
      const saved = await createVideoMark(material.material_id, { ...payload, ...locators });
      syncMarks([...(material.learning.marks || []), saved]);
      setDraft(null);
      setDraftNote("");
      setRangeStart(null);
      setMarkError("");
      window.getSelection()?.removeAllRanges();
      setTab("marks");
    } catch (caught) {
      setMarkError(caught instanceof Error ? caught.message : t("Mark could not be saved."));
    }
  };

  const persistNote = async (text: string, timeSeconds: number, quote = "") => {
    if (!text.trim()) return false;
    try {
      const saved = await addVideoNote(material.material_id, text.trim(), timeSeconds, quote);
      replaceMaterial({
        ...material,
        learning: { ...material.learning, notes: [...(material.learning.notes || []), saved] },
      });
      setNoteMessage(t("Note saved."));
      return true;
    } catch (caught) {
      setNoteMessage(caught instanceof Error ? caught.message : t("Note could not be saved."));
      return false;
    }
  };

  const saveNote = async (event: React.FormEvent) => {
    event.preventDefault();
    const saved = await persistNote(noteText, currentTime, activeCue?.text || "");
    if (saved) setNoteText("");
  };

  const saveCueNote = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!cueNoteDraft || cueNoteSaving) return;
    setCueNoteSaving(true);
    const saved = await persistNote(cueNoteText, cueNoteDraft.timeSeconds, cueNoteDraft.quote);
    setCueNoteSaving(false);
    if (saved) {
      setCueNoteDraft(null);
      setCueNoteText("");
    }
  };

  const openCueNote = (cueIndex: number) => {
    const cue = material.transcript.cues[cueIndex];
    if (!cue) return;
    setCueNoteDraft({ cueIndex, timeSeconds: cue.start, quote: cue.text });
    setCueNoteText("");
    setNoteMessage("");
  };

  const markCue = (cueIndex: number) => {
    const cue = material.transcript.cues[cueIndex];
    if (!cue) return;
    setDraft({ start_seconds: cue.start, end_seconds: cue.end, quote: cue.text });
    setDraftNote("");
    window.getSelection()?.removeAllRanges();
  };

  const handleTimeUpdate = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    const time = video.currentTime;
    const segment = material.segments.find((row) => time >= row.start && time <= row.end);
    setCurrentTime(time, segment?.locator);

    if (!video.paused && lastPlaybackTimeRef.current >= 0) {
      const delta = time - lastPlaybackTimeRef.current;
      if (delta > 0 && delta < 2.0) {
        cumulativePlayedRef.current += delta;
      }
    }
    lastPlaybackTimeRef.current = time;
  };

  const handlePauseOrSync = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const time = event.currentTarget.currentTime;
    lastPlaybackTimeRef.current = -1;
    void recordWatchProgress(material.material_id, time, cumulativePlayedRef.current).catch(() => {});
  };

  const captureSelection = () => {
    const indexes = cueIndexesFromSelection(transcriptRef.current, window.getSelection());
    const range = rangeFromCues(material.transcript.cues, indexes);
    if (range) {
      setDraft(range);
      setDraftNote("");
    }
  };

  const markCurrentTime = () => {
    const cue = activeCueIndex >= 0 ? material.transcript.cues[activeCueIndex] : undefined;
    setDraft({
      start_seconds: currentTime,
      end_seconds: currentTime,
      quote: cue?.text || "",
    });
  };

  const togglePictureInPicture = async () => {
    const video = videoRef.current as WebKitVideoElement | null;
    if (!video) return;
    const requestPip = (
      video as HTMLVideoElement & { requestPictureInPicture?: () => Promise<PictureInPictureWindow> }
    ).requestPictureInPicture;
    const setWebKitMode = video.webkitSetPresentationMode;
    showVideoCaptions(video);
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else if (typeof requestPip === "function") {
        await requestPip.call(video);
      } else if (setWebKitMode) {
        setWebKitMode.call(
          video,
          video.webkitPresentationMode === "picture-in-picture" ? "inline" : "picture-in-picture"
        );
      }
      showVideoCaptions(video);
    } catch {
      setMarkError(t("Picture in Picture is not available for this video."));
    }
  };

  const setRangeAnchor = (which: "start" | "end") => {
    if (which === "start") {
      setRangeStart(currentTime);
      return;
    }
    const start = rangeStart ?? currentTime;
    const end = currentTime;
    const from = Math.min(start, end);
    const to = Math.max(start, end);
    const quote = material.transcript.cues
      .filter((cue) => cue.end >= from && cue.start <= to)
      .map((cue) => cue.text)
      .join(" ");
    setDraft({ start_seconds: from, end_seconds: to, quote });
  };

  const extractKeyPoints = async () => {
    askAboutCurrent("extract");
    setExtracting(true);
    setMarkError("");
    try {
      const rows = await suggestVideoMarks(material.material_id, currentTime);
      setSuggestions(rows);
      setTab("marks");
    } catch (caught) {
      setMarkError(caught instanceof Error ? caught.message : t("Key points could not be extracted."));
    } finally {
      setExtracting(false);
    }
  };

  const publishToKb = async () => {
    if (!material || kbBusy) return;
    setKbBusy(true);
    setPublishMessage("");
    setMarkError("");
    try {
      const result = await publishVideoToKb(material.material_id);
      replaceMaterial(result.material);
      setPublishMessage(
        result.updated
          ? t("Published to personal knowledge base.")
          : t("Knowledge base note is already up to date."),
      );
    } catch (caught) {
      setMarkError(
        caught instanceof Error
          ? caught.message
          : t("Could not publish this video to the knowledge base."),
      );
    } finally {
      setKbBusy(false);
    }
  };

  const createInteractiveBook = async () => {
    if (!material || bookBusy) return;
    setBookBusy(true);
    setPublishMessage("");
    setMarkError("");
    try {
      const result = await createBookFromVideo(material.material_id, {
        language: (typeof navigator !== "undefined" && navigator.language.startsWith("zh")) ? "zh" : "en",
      });
      replaceMaterial(result.material);
      const bookId = String(result.book?.id || "");
      if (bookId) {
        window.location.assign(`/book?book=${encodeURIComponent(bookId)}`);
        return;
      }
      setPublishMessage(t("Interactive book draft created."));
    } catch (caught) {
      setMarkError(
        caught instanceof Error
          ? caught.message
          : t("Could not create an interactive book from this video."),
      );
    } finally {
      setBookBusy(false);
    }
  };

  const invidiousVideoUrl = invidiousPublicUrl
    ? `${invidiousPublicUrl}/watch?v=${material.source.video_id}`
    : "";

  return (
    <section
      ref={readerRef}
      data-testid="watching-reader"
      className="flex h-full min-h-0 flex-col bg-[var(--background)]"
    >
      <header className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <button
          type="button"
          onClick={() => {
            close();
            onClose();
          }}
          aria-label={t("Close")}
          className="rounded p-2 hover:bg-[var(--muted)]"
        >
          <X size={17} />
        </button>
        <button
          type="button"
          onClick={() => setShowInvidiousHome(true)}
          className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          title={t("Browse Invidious Videos")}
        >
          <Compass size={13} />
          <span>{t("Browse")}</span>
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{material.metadata.title}</h2>
          <p className="truncate text-xs text-[var(--muted-foreground)]">{material.metadata.author}</p>
        </div>
        {pipSupported && (
          <button
            type="button"
            onClick={() => void togglePictureInPicture()}
            aria-label={pipActive ? t("Exit Picture in Picture") : t("Picture in Picture")}
            title={pipActive ? t("Exit Picture in Picture") : t("Picture in Picture")}
            className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded hover:bg-[var(--muted)] ${pipActive ? "bg-[var(--muted)]" : ""}`}
          >
            <PictureInPicture2 size={16} />
          </button>
        )}
        {focusMode && (
          <button
            type="button"
            onClick={() => setAssistantPanelOpen((open) => !open)}
            aria-label={assistantPanelOpen ? t("Hide assistant") : t("Show assistant")}
            title={assistantPanelOpen ? t("Hide assistant") : t("Show assistant")}
            className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded hover:bg-[var(--muted)] ${assistantPanelOpen ? "bg-[var(--muted)]" : ""}`}
          >
            {assistantPanelOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            setFocusMode((focused) => !focused);
            if (focusMode) setAssistantPanelOpen(false);
          }}
          aria-label={focusMode ? t("Exit focus mode") : t("Focus mode")}
          title={focusMode ? t("Exit focus mode") : t("Focus mode")}
          className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded hover:bg-[var(--muted)] ${focusMode ? "bg-[var(--muted)]" : ""}`}
        >
          {focusMode ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
        <button
          type="button"
          onClick={() => void publishToKb()}
          disabled={kbBusy || bookBusy}
          title={t("Publish marks to personal knowledge base")}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {kbBusy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
          <span>{material.learning?.kb_publish ? t("Update KB") : t("Publish to KB")}</span>
        </button>
        <button
          type="button"
          onClick={() => void createInteractiveBook()}
          disabled={kbBusy || bookBusy}
          title={t("Create an interactive book from these marks")}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {bookBusy ? <Loader2 size={13} className="animate-spin" /> : <BookOpen size={13} />}
          <span>{t("Create Book")}</span>
        </button>
        <button
          type="button"
          onClick={() => void openInvidiousRenderer(material.source.video_id, currentTime)}
          disabled={openingInvidious}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
          title={t("Open in Invidious")}
        >
          {openingInvidious ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
          <span>{t("Invidious")}</span>
        </button>
        <a
          href={material.playback.official_url}
          target="_blank"
          rel="noreferrer"
          title={t("Open in YouTube")}
          className="rounded p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ExternalLink size={16} />
        </a>
      </header>
      {(publishMessage || markError) && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-xs">
          {publishMessage && <p className="text-[var(--foreground)]">{publishMessage}</p>}
          {markError && <p className="text-red-600">{markError}</p>}
        </div>
      )}
      {rendererMessage && <div className="border-b border-[var(--border)] px-3 py-1.5 text-xs">{rendererMessage}</div>}

      <div data-watching-layout className="grid min-h-0 flex-1 grid-rows-[minmax(180px,38%)_auto_1fr]">
        <div className="border-b border-[var(--border)] bg-black p-2">
          {format && !playbackError ? (
            <video
              ref={videoRef}
              className="h-full w-full object-contain"
              controls
              playsInline
              preload="metadata"
              src={timedMediaStreamUrl(material.material_id, selectedFormat)}
              onError={() => setPlaybackErrorMaterialId(material.material_id)}
              onPause={handlePauseOrSync}
              onEnded={handlePauseOrSync}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={(event) => {
                const start = material.source.entry_time_seconds || material.learning.last_position || 0;
                if (start > 0) event.currentTarget.currentTime = start;
                showVideoCaptions(event.currentTarget);
              }}
            >
              {material.transcript.cues.length > 0 && (
                <track
                  kind="captions"
                  src={timedMediaSubtitleUrl(material.material_id)}
                  srcLang={material.transcript.language || "en"}
                  label={material.transcript.language || "Subtitles"}
                  onLoad={(event) => {
                    event.currentTarget.track.mode = "showing";
                    showVideoCaptions(videoRef.current);
                  }}
                  default
                />
              )}
            </video>
          ) : playbackError ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-white">
              <p>{t("Playback failed. Open the video in YouTube or Invidious.")}</p>
              <div className="flex gap-2">
                {invidiousVideoUrl && (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded border border-white/40 px-3 py-1.5 text-xs"
                    onClick={() => void openInvidiousRenderer(material.source.video_id, currentTime)}
                    disabled={openingInvidious}
                  >
                    <Globe size={13} />
                    {t("Invidious")}
                  </button>
                )}
                <a
                  className="inline-flex items-center gap-1.5 rounded border border-white/40 px-3 py-1.5 text-xs"
                  href={material.playback.official_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={13} />
                  {t("YouTube")}
                </a>
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-white">
              {t("No compatible video stream was returned.")}
            </div>
          )}
        </div>

        <LearningTimeline marks={marks} duration={duration || 1} currentTime={currentTime} onSeek={seek} />

        <div className="flex min-h-0 flex-col">
          <div className="flex items-center gap-1 border-b border-[var(--border)] px-3 py-2 text-xs">
            <button
              type="button"
              data-testid="watching-tab-transcript"
              onClick={() => setTab("transcript")}
              className={`rounded px-2 py-1 ${tab === "transcript" ? "bg-[var(--muted)] font-semibold" : ""}`}
            >
              {t("Transcript")}
            </button>
            <button
              type="button"
              data-testid="watching-tab-notes"
              onClick={() => setTab("notes")}
              className={`rounded px-2 py-1 ${tab === "notes" ? "bg-[var(--muted)] font-semibold" : ""}`}
            >
              {t("Notes")}
            </button>
            <button
              type="button"
              data-testid="watching-tab-marks"
              onClick={() => setTab("marks")}
              className={`rounded px-2 py-1 ${tab === "marks" ? "bg-[var(--muted)] font-semibold" : ""}`}
            >
              {t("Key points")}
            </button>
            <span className="ml-auto tabular-nums text-[var(--muted-foreground)]">{formatWatchTime(currentTime)}</span>
          </div>

          {tab === "transcript" ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-3" ref={transcriptRef} onMouseUp={captureSelection} onTouchEnd={captureSelection}>
              {material.transcript.cues.length ? (
                <>
                  <div ref={actionBarRef} className="sticky top-0 z-20 mb-3 border-b border-[var(--border)] bg-[var(--background)] pb-3 shadow-sm">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => askAboutCurrent("explain")}
                        className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)]"
                      >
                        <MessageSquareText size={15} />
                        {t("Explain here")}
                      </button>
                      <button
                        type="button"
                        onClick={() => void extractKeyPoints()}
                        disabled={extracting}
                        className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)] disabled:opacity-50"
                      >
                        {extracting ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                        {t("Extract key points")}
                      </button>
                      <button
                        type="button"
                        onClick={markCurrentTime}
                        className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)]"
                      >
                        <BookmarkPlus size={15} />
                        {t("Mark here")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setRangeAnchor("start")}
                        className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)]"
                      >
                        <Flag size={15} />
                        {rangeStart === null ? t("Set start") : `${t("Start")}: ${formatWatchTime(rangeStart)}`}
                      </button>
                      <button
                        type="button"
                        onClick={() => setRangeAnchor("end")}
                        className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)]"
                      >
                        {t("Set end")}
                      </button>
                    </div>
                    {noteMessage && <p className="mb-3 text-xs text-[var(--muted-foreground)]">{noteMessage}</p>}
                    {draft && (
                      <div className="mt-3 rounded border border-[var(--border)] bg-[var(--background)] p-2">
                        <p className="mb-2 text-xs text-[var(--muted-foreground)]">
                          {formatWatchTime(draft.start_seconds)}
                          {draft.end_seconds !== draft.start_seconds ? ` – ${formatWatchTime(draft.end_seconds)}` : ""}
                        </p>
                        <div className="mb-2 flex flex-wrap gap-2">
                          {(["key_point", "question", "review"] as VideoMarkKind[]).map((kind) => (
                          <button
                            key={kind}
                            type="button"
                            className="rounded px-2 py-1 text-xs text-white"
                            data-testid={`watching-mark-${kind}`}
                            style={{ backgroundColor: VIDEO_MARK_COLORS[kind] }}
                            onClick={() => void saveMark({ ...draft, kind, note: draftNote, author: "user" })}
                          >
                            {kind === "question" ? t("Question mark") : kind === "review" ? t("Review later") : t("Key point")}
                          </button>
                          ))}
                          <button
                          type="button"
                          className="rounded border border-[var(--border)] px-2 py-1 text-xs"
                          onClick={() => {
                            setDraft(null);
                            setDraftNote("");
                            window.getSelection()?.removeAllRanges();
                          }}
                        >
                          {t("Cancel")}
                          </button>
                        </div>
                        <input
                          value={draftNote}
                          onChange={(event) => setDraftNote(event.target.value)}
                          placeholder={t("Optional note for this mark")}
                          className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs"
                        />
                      </div>
                    )}
                  </div>
                  {material.transcript.cues.map((cue, index) => {
                    const cueActive = activeCueIndex === index;
                    const marked = marks.some(
                      (mark) => mark.end_seconds >= cue.start && mark.start_seconds <= cue.end
                    );
                    const cueNotes = (material.learning.notes || []).filter(
                      (note) => noteMatchesCue(note, cue)
                    );
                    const noteOpen = cueNoteDraft?.cueIndex === index;
                    return (
                      <div
                        key={`${cue.start}-${index}`}
                        data-cue-index={index}
                        data-active={cueActive ? "true" : "false"}
                        data-testid={`watching-cue-${index}`}
                        aria-current={cueActive ? "true" : undefined}
                        className={`mb-1 flex w-full items-start gap-2 rounded border-l-4 p-2 text-sm ${cueActive ? "border-amber-600 bg-amber-500/15 font-medium" : "border-transparent hover:bg-[var(--muted)]/60"} ${marked ? "ring-1 ring-amber-700/40" : ""}`}
                      >
                        <button
                          type="button"
                          onClick={() => seek(cue.start)}
                          className="min-h-11 shrink-0 py-3 font-mono text-xs text-[var(--muted-foreground)]"
                        >
                          {formatWatchTime(cue.start)}
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start gap-1">
                            <span data-testid="watching-cue-text" className="min-w-0 flex-1 select-text py-2 leading-relaxed">
                              {cue.text}
                            </span>
                            <div className="flex shrink-0 items-center gap-1">
                              <button
                                type="button"
                                data-testid={`watching-cue-note-${index}`}
                                aria-label={`${t("Add note to this subtitle")} ${formatWatchTime(cue.start)}`}
                                title={t("Add note to this subtitle")}
                                className={`inline-flex h-11 w-11 items-center justify-center rounded hover:bg-[var(--background)] ${cueNotes.length ? "text-amber-700" : "text-[var(--muted-foreground)]"}`}
                                onClick={() => openCueNote(index)}
                              >
                                <StickyNote size={16} />
                              </button>
                              <button
                                type="button"
                                data-testid={`watching-cue-mark-${index}`}
                                aria-label={`${t("Mark this subtitle")} ${formatWatchTime(cue.start)}`}
                                title={t("Mark this subtitle")}
                                className={`inline-flex h-11 w-11 items-center justify-center rounded hover:bg-[var(--background)] ${marked ? "text-amber-700" : "text-[var(--muted-foreground)]"}`}
                                onClick={() => markCue(index)}
                              >
                                <BookmarkPlus size={16} />
                              </button>
                            </div>
                          </div>

                          {noteOpen && (
                            <form className="mt-2 border-l-2 border-amber-600 pl-2" onSubmit={(event) => void saveCueNote(event)}>
                              <textarea
                                autoFocus
                                rows={2}
                                value={cueNoteText}
                                onChange={(event) => setCueNoteText(event.target.value)}
                                placeholder={t("Write a note about this subtitle...")}
                                className="w-full resize-y rounded border border-[var(--border)] bg-[var(--background)] px-2 py-2 text-sm"
                              />
                              <div className="mt-2 flex items-center justify-end gap-2">
                                <button
                                  type="button"
                                  aria-label={t("Cancel")}
                                  title={t("Cancel")}
                                  className="inline-flex h-9 w-9 items-center justify-center rounded border border-[var(--border)]"
                                  onClick={() => {
                                    setCueNoteDraft(null);
                                    setCueNoteText("");
                                  }}
                                >
                                  <X size={15} />
                                </button>
                                <button
                                  type="submit"
                                  disabled={!cueNoteText.trim() || cueNoteSaving}
                                  className="inline-flex min-h-9 items-center gap-1 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs text-[var(--background)] disabled:opacity-50"
                                >
                                  {cueNoteSaving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                  {t("Save note")}
                                </button>
                              </div>
                            </form>
                          )}

                          {cueNotes.length > 0 && !noteOpen && (
                            <div className="mt-1 space-y-1 text-xs text-[var(--muted-foreground)]">
                              {cueNotes.map((note) => (
                                <p key={note.note_id} className="flex items-start gap-1.5">
                                  <StickyNote size={13} className="mt-0.5 shrink-0 text-amber-700" />
                                  <span>{note.text}</span>
                                </p>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </>
              ) : (
                <div className="space-y-3 p-2 text-sm text-[var(--muted-foreground)]">
                  <p>{material.transcript.fetch?.status === "fetching" || material.transcript.fetch?.status === "queued" ? t("Preparing YouTube subtitles…") : t("No subtitles are available for this video.")}</p>
                  <button
                    type="button"
                    disabled={youtubeConnecting}
                    className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 disabled:opacity-50"
                    onClick={() => void connectYouTubeForSubtitles()}
                  >
                    {youtubeConnecting ? <Loader2 size={15} className="animate-spin" /> : <Globe size={15} />}
                    {t("Connect YouTube")}
                  </button>
                  {youtubeMessage && <p>{youtubeMessage}</p>}
                  <button
                    type="button"
                    disabled={Boolean(jobId)}
                    className="inline-flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 disabled:opacity-50"
                    onClick={() => {
                      void createTranscriptJob(material.material_id)
                        .then((job) => {
                          setJobId(job.job_id);
                          setJobMessage(t("Subtitle generation submitted."));
                        })
                        .catch((caught) =>
                          setJobMessage(caught instanceof Error ? caught.message : t("Subtitle generation failed."))
                        );
                    }}
                  >
                    <FilePlus2 size={15} />
                    {t("Generate subtitles")}
                  </button>
                  {jobMessage && <p>{jobMessage}</p>}
                </div>
              )}
            </div>
          ) : tab === "notes" ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm text-[var(--muted-foreground)]">
              <form onSubmit={saveNote} className="flex gap-2">
                <input
                  value={noteText}
                  onChange={(event) => setNoteText(event.target.value)}
                  placeholder={t("Write a note about this timestamp...")}
                  className="min-w-0 flex-1 rounded border border-[var(--border)] bg-transparent px-3 py-2"
                />
                <button
                  type="submit"
                  disabled={!noteText.trim()}
                  aria-label={t("Save note")}
                  className="inline-flex items-center gap-2 rounded bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
                >
                  <Plus size={15} />
                  {t("Save note")}
                </button>
              </form>
              {noteMessage && <p className="mt-2">{noteMessage}</p>}
              {material.learning.notes?.length ? (
                <div className="mt-4 space-y-2">
                  {[...material.learning.notes].reverse().map((note) => (
                    <button
                      type="button"
                      key={note.note_id}
                      onClick={() => seek(note.time_seconds)}
                      className="block w-full rounded border border-[var(--border)] p-2 text-left hover:bg-[var(--muted)]"
                    >
                      <span className="block font-mono text-xs text-[var(--muted-foreground)]">
                        {formatWatchTime(note.time_seconds)}
                      </span>
                      {note.quote && <span className="mt-1 block border-l-2 border-[var(--border)] pl-2 text-xs">{note.quote}</span>}
                      <span className="mt-1 block text-[var(--foreground)]">{note.text}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="mt-4">{t("No notes yet.")}</p>
              )}
            </div>
          ) : (
            <KeyPointsPanel
              marks={marks}
              suggestions={suggestions}
              currentTime={currentTime}
              durationEndMark={endPrompt}
              error={markError}
              onSeek={seek}
              onDelete={(markId) => {
                void deleteVideoMark(material.material_id, markId)
                  .then(() => syncMarks(marks.filter((mark) => mark.mark_id !== markId)))
                  .catch((caught) => setMarkError(caught instanceof Error ? caught.message : t("Mark could not be deleted.")));
              }}
              onReviewed={(mark) => {
                void patchVideoMark(material.material_id, mark.mark_id, { reviewed: true })
                  .then((saved) => syncMarks(marks.map((row) => (row.mark_id === saved.mark_id ? saved : row))))
                  .then(() => setEndPrompt(null))
                  .catch((caught) => setMarkError(caught instanceof Error ? caught.message : t("Mark could not be saved.")));
              }}
              onSaveSuggestion={(suggestion) => {
                void saveMark({ ...suggestion, author: "assistant" }).then(() => {
                  setSuggestions((rows) => rows.filter((row) => row !== suggestion));
                });
              }}
              onDismissEnd={() => setEndPrompt(null)}
              onReplayEnd={(mark) => {
                setEndPrompt(null);
                seek(mark.start_seconds);
              }}
            />
          )}
        </div>
      </div>
      {focusMode && assistantPanelOpen && (
        <button
          type="button"
          onClick={() => setAssistantPanelOpen(false)}
          aria-label={t("Hide assistant")}
          title={t("Hide assistant")}
          className="fixed left-1 top-1 z-[102] inline-flex h-8 w-8 items-center justify-center rounded bg-[var(--card)] text-[var(--foreground)] shadow md:hidden"
        >
          <PanelRightClose size={15} />
        </button>
      )}
    </section>
  );
}
