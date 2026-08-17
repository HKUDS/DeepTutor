"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  CircleDot,
  Clock,
  ListChecks,
  Loader2,
  Play,
  RefreshCw,
  Save,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import {
  translationTaskApi,
  type TranslationSourceType,
  type TranslationTask,
  type TranslationTaskBoard as Board,
  type TranslationTaskEvent,
  type TranslationTaskStatus,
  type TranslationGlossaryEntry,
} from "@/lib/translation-tasks-api";

interface TranslationTaskBoardProps {
  sourceType?: TranslationSourceType;
  sourceId?: string;
  chapterId?: string;
  compact?: boolean;
  onClose?: () => void;
  onBoardLoaded?: (board: Board) => void;
  onGroupTranslated?: (task: TranslationTask & { translation?: string }) => void;
}

function nextSummary(
  summary: Board["summary"],
  oldStatus: TranslationTaskStatus,
  status: TranslationTaskStatus,
) {
  const delta = (key: keyof Board["summary"], value: number) =>
    Math.max(0, Number(summary[key] || 0) + value);
  return {
    ...summary,
    [oldStatus]: delta(oldStatus as keyof Board["summary"], -1),
    [status]: delta(status as keyof Board["summary"], 1),
    [`filtered_${oldStatus}`]: delta(`filtered_${oldStatus}` as keyof Board["summary"], -1),
    [`filtered_${status}`]: delta(`filtered_${status}` as keyof Board["summary"], 1),
  };
}

function applyTask(board: Board, task: TranslationTask): Board {
  const previous = board.tasks.find((item) => item.id === task.id);
  if (previous?.status === task.status) {
    return {
      ...board,
      tasks: board.tasks.map((item) => (item.id === task.id ? task : item)),
    };
  }
  const oldStatus = previous?.status;
  return {
    ...board,
    summary: oldStatus
      ? nextSummary(board.summary, oldStatus, task.status)
      : board.summary,
    tasks: board.tasks.some((item) => item.id === task.id)
      ? board.tasks.map((item) => (item.id === task.id ? task : item))
      : [task, ...board.tasks],
  };
}

export default function TranslationTaskBoardPanel({
  sourceType,
  sourceId,
  chapterId,
  compact = false,
  onClose,
  onBoardLoaded,
  onGroupTranslated,
}: TranslationTaskBoardProps) {
  const { t } = useTranslation();
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  const [savingGlossary, setSavingGlossary] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [glossaryDraft, setGlossaryDraft] = useState<TranslationGlossaryEntry[] | null>(null);
  const boardLoadedRef = useRef(onBoardLoaded);
  const streamAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    boardLoadedRef.current = onBoardLoaded;
  }, [onBoardLoaded]);

  const applyBoard = useCallback((next: Board) => {
    setBoard(next);
    setGlossaryDraft(null);
    boardLoadedRef.current?.(next);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      applyBoard(await translationTaskApi.list({ sourceType, sourceId, chapterId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [applyBoard, chapterId, sourceId, sourceType]);

  useEffect(() => {
    void load();
  }, [load]);

  const closeStream = useCallback(() => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
  }, []);

  useEffect(() => {
    closeStream();
    setRunning(false);
    setRunningRunId(null);
  }, [chapterId, closeStream, sourceId, sourceType]);

  const close = useCallback(() => {
    closeStream();
    onClose?.();
  }, [closeStream, onClose]);

  useEffect(() => closeStream, [closeStream]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close]);

  const handleEvent = useCallback(
    (event: TranslationTaskEvent) => {
      if (event.parse_error) {
        setError(t("Ignoring an invalid translation stream event."));
        return;
      }
      if (event.type === "snapshot" && event.board) {
        setBoard(event.board);
        return;
      }
      if (event.type === "run_cancelled" || event.type === "run_completed") {
        setRunning(false);
        if (event.run_id === runningRunId) {
          setRunningRunId(null);
        }
      }
      if (event.task) {
        setBoard((current) => (current ? applyTask(current, event.task!) : current));
        if (event.type === "group_translated") onGroupTranslated?.(event.task);
      }
    },
    [onGroupTranslated, t, runningRunId],
  );

  const handlePlanAndRun = async () => {
    const controller = new AbortController();
    streamAbortRef.current = controller;
    setRunning(true);
    setError(null);
    try {
      if (sourceType && sourceId) {
        await translationTaskApi.plan(sourceType, sourceId);
      }
      const started = await translationTaskApi.run({
        sourceType,
        sourceId,
        chapterId,
        limit: compact ? 4 : 8,
      });
      setRunningRunId(started.run_id);
      applyBoard(started);
      if (started.started && started.run_id) {
        await translationTaskApi.streamRun(started.run_id, {
          signal: controller.signal,
          onEvent: handleEvent,
        });
      }
      const latest = await translationTaskApi.list({ sourceType, sourceId, chapterId });
      applyBoard(latest);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : String(err));
        try {
          applyBoard(await translationTaskApi.list({ sourceType, sourceId, chapterId }));
        } catch {
          // Keep the visible partial board on refresh failure.
        }
      }
    } finally {
      streamAbortRef.current = null;
      setRunning(false);
      setRunningRunId(null);
    }
  };

  const handleCancelRun = async () => {
    if (!runningRunId) return;
    setError(null);
    try {
      setRunning(true);
      closeStream();
      await translationTaskApi.cancelRun(runningRunId);
      setRunningRunId(null);
      applyBoard(await translationTaskApi.list({ sourceType, sourceId, chapterId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const handleRetryFailed = async () => {
    setRunning(true);
    try {
      applyBoard(await translationTaskApi.retryFailed(sourceType, sourceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const saveGlossary = async () => {
    if (!sourceType || !sourceId || !glossaryDraft) return;
    setSavingGlossary(true);
    try {
      applyBoard(
        await translationTaskApi.updateGlossary(sourceType, sourceId, glossaryDraft),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingGlossary(false);
    }
  };

  const statusIcon = (status: string) => {
    if (status === "completed") return <CheckCircle2 className="size-3.5 text-emerald-600" />;
    if (status === "running") return <Loader2 className="size-3.5 animate-spin text-blue-600" />;
    if (status === "failed") return <XCircle className="size-3.5 text-red-600" />;
    return <Clock className="size-3.5 text-amber-600" />;
  };

  const visibleTasks = useMemo(() => board?.tasks.slice(0, compact ? 8 : 100) ?? [], [board, compact]);
  const summary = board?.summary;
  const glossary = glossaryDraft ?? board?.glossary ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ListChecks className="size-4" />
          {t("Translation Tasks")}
          {running && <Loader2 className="size-3.5 animate-spin text-blue-600" />}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handlePlanAndRun()}
            disabled={running || summary?.is_running}
            className="flex items-center gap-1 rounded-lg bg-[var(--primary)] px-2.5 py-1.5 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {running || summary?.is_running ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
            {chapterId ? t("Run this chapter") : t("Start translation")}
          </button>
          <button
            type="button"
            onClick={() => void handleCancelRun()}
            disabled={runningRunId === null || running === false}
            className="flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-700 disabled:opacity-50"
          >
            <XCircle className="size-3.5" />
            {t("Cancel run")}
          </button>
          <button
            type="button"
            onClick={() => void handleRetryFailed()}
            disabled={running || !summary?.filtered_failed}
            className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs disabled:opacity-50"
          >
            <RefreshCw className="size-3.5" />
            {t("Retry failed")}
          </button>
          {onClose && (
            <button
              type="button"
              onClick={close}
              autoFocus
              aria-label={t("Close")}
              className="rounded-lg border border-[var(--border)] p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </div>
      {error ? (
        <div className="m-3 rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      ) : loading ? (
        <div className="flex flex-1 items-center justify-center py-10">
          <Loader2 className="size-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : board ? (
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            {(["queued", "running", "completed", "failed"] as const).map((status) => (
              <div key={status} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
                <div className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
                  {statusIcon(status)}
                  {t(status === "queued" ? "Queued" : status.charAt(0).toUpperCase() + status.slice(1))}
                </div>
                <div className="mt-1 text-lg font-semibold">
                  {status === "queued" ? summary?.filtered_queued : status === "running" ? summary?.filtered_running : status === "completed" ? summary?.filtered_completed : summary?.filtered_failed}
                </div>
              </div>
            ))}
          </div>
          {!compact && glossary.length > 0 && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
              <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2 text-xs font-semibold">
                <span className="flex items-center gap-1.5"><ShieldCheck className="size-3.5" />{t("Terminology")}</span>
                <button type="button" onClick={() => void saveGlossary()} disabled={savingGlossary || !glossaryDraft} className="flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 disabled:opacity-50">
                  {savingGlossary ? <Loader2 className="size-3 animate-spin" /> : <Save className="size-3" />}
                  {t("Save")}
                </button>
              </div>
              <div className="max-h-72 overflow-y-auto">
                {glossary.map((entry, index) => {
                  const decision = entry.decision ?? (entry.approved ? "approved" : "candidate");
                  return (
                    <div key={entry.term} className="grid grid-cols-1 gap-2 border-b border-[var(--border)] px-3 py-2 text-xs last:border-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_100px_110px]">
                      <div className="min-w-0 truncate font-medium" title={entry.term}>{entry.term}</div>
                      <input
                        value={entry.translation}
                        onChange={(event) => {
                          const next = [...glossary];
                          next[index] = { ...entry, translation: event.target.value };
                          setGlossaryDraft(next);
                        }}
                        className="h-8 min-w-0 rounded border border-[var(--border)] bg-[var(--background)] px-2"
                      />
                      <label className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
                        <input
                          type="checkbox"
                          checked={entry.protected}
                          onChange={(event) => {
                            const next = [...glossary];
                            next[index] = { ...entry, protected: event.target.checked };
                            setGlossaryDraft(next);
                          }}
                        />
                        {t("Locked")}
                      </label>
                      <select
                        value={decision}
                        onChange={(event) => {
                          const nextDecision = event.target.value as TranslationGlossaryEntry["decision"];
                          const next = [...glossary];
                          next[index] = {
                            ...entry,
                            decision: nextDecision,
                            approved: nextDecision === "approved",
                          };
                          setGlossaryDraft(next);
                        }}
                        className="h-8 rounded border border-[var(--border)] bg-[var(--background)] px-1"
                      >
                        <option value="candidate">{t("Candidate")}</option>
                        <option value="approved">{t("Approved")}</option>
                        <option value="rejected">{t("Rejected")}</option>
                      </select>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {!compact && board.sources.length > 0 && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--card)]">
              {board.sources.map((source) => (
                <div key={`${source.source_type}:${source.source_id}`} className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-2 text-xs last:border-0">
                  <span className="min-w-0 flex-1 truncate font-medium">{source.label}</span>
                  {source.all_translated ? (
                    <span className="flex items-center gap-1 text-emerald-600"><CheckCircle2 className="size-3.5" />{t("All translated")}</span>
                  ) : (
                    <span className="text-[var(--muted-foreground)]">{source.translated_units}/{source.total_units}</span>
                  )}
                </div>
              ))}
            </div>
          )}
          {visibleTasks.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-[var(--muted-foreground)]">
              <CircleDot className="size-5" />
              {t("No translation tasks")}
            </div>
          ) : (
            <div className="space-y-2">
              {visibleTasks.map((task) => (
                <div key={task.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{task.source_label} · {task.title}</div>
                      <div className="mt-0.5 line-clamp-2 text-[11px] text-[var(--muted-foreground)]">{task.source_text}</div>
                      {task.error && <div className="mt-1 line-clamp-2 text-[11px] text-red-600">{task.error}</div>}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {statusIcon(task.status)}
                      {task.status === "failed" && (
                        <button type="button" onClick={() => void translationTaskApi.retry(task.id).then(applyBoard)} className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px]">
                          {t("Retry")}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
