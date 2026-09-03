"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Captions,
  ExternalLink,
  Loader2,
  Pencil,
  Play,
  RotateCcw,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useWatching } from "@/context/WatchingContext";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import type { PlayerController } from "@/lib/video-player-controller";
import {
  createVideoNote,
  deleteVideoNote,
  listVideoNotes,
  saveVideoProgress,
  updateVideoNote,
  type VideoNote,
} from "@/lib/video-learning-api";
import { videoTimeFromHref } from "@/lib/watching-citations";
import { WatchingPlayer } from "./WatchingPlayer";

export const WATCHING_ASK_EVENT = "dt:watching-ask";

type WatchTab = "transcript" | "notes";

export function WatchingPane({ onClose }: { onClose(): void }) {
  const { t } = useTranslation();
  const {
    material,
    loading,
    error,
    lastUrl,
    openUrl,
    refresh,
    refreshTranscript,
    close,
    reportTime,
    clearError,
    setActive,
  } = useWatching();
  const materialId = material?.material_id ?? null;
  const [input, setInput] = useState("");
  const [playerError, setPlayerError] = useState<string | null>(null);
  const [tab, setTab] = useState<WatchTab>("transcript");
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [notes, setNotes] = useState<VideoNote[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const controllerRef = useRef<PlayerController | null>(null);
  const activeMaterialIdRef = useRef(materialId);
  const lastSavedRef = useRef(0);
  const stateRef = useRef({ time: 0, duration: 0 });
  activeMaterialIdRef.current = materialId;

  useEffect(() => {
    setActive(true);
    return () => setActive(false);
  }, [setActive]);

  const persist = useCallback(() => {
    if (!material) return;
    const current = stateRef.current;
    if (current.time <= 0) return;
    void saveVideoProgress(
      material.material_id,
      current.time,
      current.duration,
    ).catch(() => undefined);
    lastSavedRef.current = current.time;
  }, [material]);

  const handleTime = useCallback(
    (nextTime: number, nextDuration: number) => {
      stateRef.current = { time: nextTime, duration: nextDuration };
      setTime(nextTime);
      setDuration(nextDuration);
      reportTime(nextTime);
      if (Math.abs(nextTime - lastSavedRef.current) >= 5) persist();
    },
    [persist, reportTime],
  );

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") persist();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      persist();
    };
  }, [persist]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor = (event.target as HTMLElement | null)?.closest?.(
        "a[href]",
      ) as HTMLAnchorElement | null;
      const seconds = videoTimeFromHref(anchor?.getAttribute("href"));
      if (seconds === null) return;
      event.preventDefault();
      controllerRef.current?.seek(seconds);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  const cue = useMemo(
    () =>
      material?.transcript.cues.find(
        (row) => time >= row.start && time <= row.end,
      ),
    [material, time],
  );

  const submit = async (providerOverride?: "youtube") => {
    const url = (providerOverride ? lastUrl || input : input).trim();
    if (!url) return;
    setPlayerError(null);
    try {
      await openUrl(url, "", providerOverride);
    } catch {
      // The context owns the user-facing error.
    }
  };

  const askHere = () => {
    if (!material || !cue) return;
    window.dispatchEvent(
      new CustomEvent(WATCHING_ASK_EVENT, {
        detail: { timeSeconds: time, text: cue.text },
      }),
    );
  };

  useEffect(() => {
    let cancelled = false;
    setNotes([]);
    setNotesError(null);
    setNoteDraft("");
    setEditingNoteId(null);
    setEditingDraft("");
    setPendingDeleteId(null);
    if (!materialId) {
      setNotesLoading(false);
      return () => {
        cancelled = true;
      };
    }
    setNotesLoading(true);
    void (async () => {
      try {
        const loaded = await listVideoNotes(materialId);
        if (!cancelled) setNotes(loaded);
      } catch (caught) {
        if (!cancelled) {
          setNotesError(
            caught instanceof Error
              ? caught.message
              : t("Notes could not be loaded."),
          );
        }
      } finally {
        if (!cancelled) setNotesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [materialId, t]);

  const sortNotes = (rows: VideoNote[]) =>
    [...rows].sort(
      (left, right) =>
        left.time_seconds - right.time_seconds ||
        left.created_at - right.created_at ||
        left.note_id.localeCompare(right.note_id),
    );

  const addNote = async () => {
    if (!material || !noteDraft.trim() || noteBusy) return;
    const requestedMaterialId = material.material_id;
    setNoteBusy(true);
    setNotesError(null);
    try {
      const saved = await createVideoNote(
        requestedMaterialId,
        noteDraft.trim(),
        time,
      );
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotes((current) => sortNotes([...current, saved]));
      setNoteDraft("");
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotesError(
        caught instanceof Error ? caught.message : t("Note was not saved."),
      );
    } finally {
      setNoteBusy(false);
    }
  };

  const saveEditedNote = async () => {
    if (!material || !editingNoteId || !editingDraft.trim() || noteBusy) return;
    const requestedMaterialId = material.material_id;
    setNoteBusy(true);
    setNotesError(null);
    try {
      const saved = await updateVideoNote(
        requestedMaterialId,
        editingNoteId,
        editingDraft.trim(),
      );
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotes((current) =>
        sortNotes(
          current.map((note) =>
            note.note_id === saved.note_id ? saved : note,
          ),
        ),
      );
      setEditingNoteId(null);
      setEditingDraft("");
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotesError(
        caught instanceof Error ? caught.message : t("Note was not saved."),
      );
    } finally {
      setNoteBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!material || !pendingDeleteId || noteBusy) return;
    const requestedMaterialId = material.material_id;
    setNoteBusy(true);
    setNotesError(null);
    try {
      await deleteVideoNote(requestedMaterialId, pendingDeleteId);
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotes((current) =>
        current.filter((note) => note.note_id !== pendingDeleteId),
      );
      if (editingNoteId === pendingDeleteId) {
        setEditingNoteId(null);
        setEditingDraft("");
      }
      setPendingDeleteId(null);
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return;
      setNotesError(
        caught instanceof Error ? caught.message : t("Note was not deleted."),
      );
    } finally {
      setNoteBusy(false);
    }
  };

  const closePane = () => {
    persist();
    close();
    onClose();
  };

  const effectiveError = error || playerError;
  const openNativeYouTube = useCallback(async () => {
    if (!material) return;
    setPlayerError(null);
    clearError();
    try {
      await openUrl(material.source.url, "", "youtube");
    } catch {
      // The context owns the user-facing error.
    }
  }, [clearError, material, openUrl]);

  const refreshProvider = useCallback(async () => {
    setPlayerError(null);
    await refresh();
  }, [refresh]);

  const retryTranscript = useCallback(async () => {
    setPlayerError(null);
    await refreshTranscript();
  }, [refreshTranscript]);

  const handleController = useCallback(
    (controller: PlayerController | null) => {
      controllerRef.current = controller;
    },
    [],
  );
  return (
    <section className="flex h-full min-w-0 flex-col border-r border-[var(--border)] bg-[var(--background)]">
      <header className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-semibold">{t("Immersive Watching")}</h2>
          <p className="truncate text-xs text-[var(--muted-foreground)]">
            {material?.metadata.title || t("Native YouTube learning")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refreshProvider()}
          disabled={!material || loading}
          className="rounded-md p-2 hover:bg-[var(--muted)]"
          aria-label={t("Refresh provider")}
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={closePane}
          className="rounded-md p-2 hover:bg-[var(--muted)]"
          aria-label={t("Close video learning")}
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {!material && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
          <Play className="h-10 w-10 text-red-500" />
          <div>
            <h3 className="font-medium">
              {t("Open a YouTube learning video")}
            </h3>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("Paste a watch, Shorts, Live, Embed, or youtu.be link.")}
            </p>
          </div>
          <form
            className="flex w-full max-w-xl gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={t("YouTube URL")}
              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-lg bg-red-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t("Open")
              )}
            </button>
          </form>
          {effectiveError && (
            <div
              role="alert"
              className="w-full max-w-xl rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-left text-sm"
            >
              <div className="flex gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{effectiveError}</span>
              </div>
              {lastUrl && (
                <button
                  type="button"
                  onClick={() => {
                    clearError();
                    void submit("youtube");
                  }}
                  className="mt-3 rounded-md border border-[var(--border)] px-3 py-1.5 font-medium"
                >
                  {t("Use native YouTube for this video")}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {material && (
        <div className="flex min-h-0 flex-1 flex-col">
          <WatchingPlayer
            key={`${material.material_id}:${material.playback.provider}`}
            playback={material.playback}
            transcriptLanguage={material.transcript.language || "en"}
            onController={handleController}
            onTime={handleTime}
            onPersist={persist}
            onError={setPlayerError}
          />
          {effectiveError && (
            <div
              role="alert"
              className="m-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
            >
              {effectiveError}
              {material.playback.provider === "invidious" && (
                <button
                  type="button"
                  onClick={() => void openNativeYouTube()}
                  className="ml-3 rounded border border-[var(--border)] px-2 py-1"
                >
                  {t("Use native YouTube")}
                </button>
              )}
            </div>
          )}
          <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3 text-sm">
            <span className="tabular-nums">
              {formatTime(time)} /{" "}
              {formatTime(duration || material.metadata.duration_seconds)}
            </span>
            <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs">
              {material.playback.provider === "youtube"
                ? "YouTube"
                : "Invidious"}
            </span>
            <a
              href={`https://youtu.be/${material.source.video_id}?t=${Math.floor(time)}`}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-xs text-blue-600"
            >
              {t("Open official")} <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div
              className="mb-3 grid w-full max-w-56 grid-cols-2 rounded-lg bg-[var(--muted)] p-1"
              role="tablist"
              aria-label={t("Video learning panels")}
            >
              {(["transcript", "notes"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={tab === item}
                  onClick={() => {
                    setTab(item);
                    setEditingNoteId(null);
                  }}
                  className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium ${tab === item ? "bg-[var(--background)] shadow-sm" : "text-[var(--muted-foreground)]"}`}
                >
                  {item === "transcript" ? (
                    <>
                      <Captions className="h-3.5 w-3.5" />
                      {t("Transcript")}
                    </>
                  ) : (
                    <>
                      <StickyNote className="h-3.5 w-3.5" />
                      {t("Video notes")}
                    </>
                  )}
                </button>
              ))}
            </div>

            {tab === "transcript" ? (
              material.transcript.status !== "ready" ? (
                <div className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">
                  <p>
                    {t(
                      "Transcript learning is unavailable ({{reason}}). Playback still works, but Explain here is disabled.",
                      {
                        reason: material.transcript.reason || t("no captions"),
                      },
                    )}
                  </p>
                  {material.playback.provider === "invidious" && (
                    <button
                      type="button"
                      onClick={() => void retryTranscript()}
                      disabled={loading}
                      className="mt-3 rounded border border-[var(--border)] px-2 py-1 font-medium text-[var(--foreground)] disabled:opacity-50"
                    >
                      {t("Retry captions")}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={askHere}
                    disabled={!cue}
                    className="mb-3 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                  >
                    {t("Explain here")}
                  </button>
                  <div className="space-y-1">
                    {material.transcript.cues.map((row, index) => {
                      const active = row === cue;
                      return (
                        <button
                          key={`${row.start}-${index}`}
                          type="button"
                          onClick={() => controllerRef.current?.seek(row.start)}
                          className={`flex w-full gap-3 rounded-md px-2 py-1.5 text-left text-sm ${active ? "bg-blue-500/15 ring-1 ring-blue-500/30" : "hover:bg-[var(--muted)]"}`}
                        >
                          <span className="shrink-0 tabular-nums text-blue-600">
                            {formatTime(row.start)}
                          </span>
                          <span>{row.text}</span>
                        </button>
                      );
                    })}
                  </div>
                </>
              )
            ) : (
              <div className="space-y-3">
                <form
                  className="space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void addNote();
                  }}
                >
                  <textarea
                    value={noteDraft}
                    onChange={(event) => setNoteDraft(event.target.value)}
                    placeholder={t("Note at {{time}}", {
                      time: formatTime(time),
                    })}
                    className="min-h-20 w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={noteBusy || !noteDraft.trim()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                  >
                    {noteBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4" />
                    )}
                    {t("Add video note")}
                  </button>
                </form>

                {notesError && (
                  <p
                    role="alert"
                    className="rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-2 text-sm text-[var(--destructive)]"
                  >
                    {notesError}
                  </p>
                )}

                {notesLoading ? (
                  <p className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("Loading notes.")}
                  </p>
                ) : notes.length ? (
                  notes.map((note) => (
                    <article
                      key={`${note.notebook_id}:${note.note_id}`}
                      className="rounded-lg border border-[var(--border)] p-3"
                    >
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            controllerRef.current?.seek(note.time_seconds)
                          }
                          className="shrink-0 rounded px-1.5 py-0.5 font-mono text-xs tabular-nums text-blue-600 hover:bg-blue-500/10"
                        >
                          {formatTime(note.time_seconds)}
                        </button>
                        <div className="min-w-0 flex-1">
                          {editingNoteId === note.note_id ? (
                            <textarea
                              value={editingDraft}
                              onChange={(event) =>
                                setEditingDraft(event.target.value)
                              }
                              aria-label={t("Edit note at {{time}}", {
                                time: formatTime(note.time_seconds),
                              })}
                              className="min-h-20 w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
                            />
                          ) : (
                            <p className="whitespace-pre-wrap text-sm">
                              {note.body}
                            </p>
                          )}
                          {note.quote && (
                            <blockquote className="mt-2 border-l-2 border-[var(--border)] pl-2 text-xs text-[var(--muted-foreground)]">
                              {note.quote}
                            </blockquote>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          {editingNoteId === note.note_id ? (
                            <>
                              <button
                                type="button"
                                onClick={() => void saveEditedNote()}
                                disabled={noteBusy || !editingDraft.trim()}
                                className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                                aria-label={t("Save video note")}
                              >
                                <Check className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingNoteId(null)}
                                disabled={noteBusy}
                                className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                                aria-label={t("Cancel")}
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setEditingNoteId(note.note_id);
                                setEditingDraft(note.body);
                              }}
                              disabled={noteBusy}
                              className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                              aria-label={t("Edit note at {{time}}", {
                                time: formatTime(note.time_seconds),
                              })}
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setPendingDeleteId(note.note_id)}
                            disabled={noteBusy}
                            className="rounded-md p-1.5 text-[var(--destructive)] hover:bg-[var(--destructive)]/10 disabled:opacity-50"
                            aria-label={t("Delete note at {{time}}", {
                              time: formatTime(note.time_seconds),
                            })}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  !notesError && <p className="text-sm">{t("No notes yet.")}</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(pendingDeleteId)}
        title={t("Delete this note?")}
        confirmLabel={t("Delete")}
        tone="danger"
        busy={noteBusy}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDeleteId(null)}
      >
        {t("This note will be removed from Video Learning.")}
      </ConfirmDialog>
    </section>
  );
}

function formatTime(value: number): string {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}
