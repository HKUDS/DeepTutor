"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, CircleDot, Clock, ListChecks, Loader2, Play, RefreshCw, XCircle } from "lucide-react";
import {
  translationTaskApi,
  type TranslationSourceType,
  type TranslationTask,
  type TranslationTaskBoard as Board,
} from "@/lib/translation-tasks-api";

interface TranslationTaskBoardProps {
  sourceType?: TranslationSourceType;
  sourceId?: string;
  chapterId?: string;
  compact?: boolean;
  onBoardLoaded?: (board: Board) => void;
  onGroupTranslated?: (task: TranslationTask & { translation?: string }) => void;
}

export default function TranslationTaskBoardPanel({
  sourceType,
  sourceId,
  chapterId,
  compact = false,
  onBoardLoaded,
  onGroupTranslated,
}: TranslationTaskBoardProps) {
  const { t } = useTranslation();
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boardLoadedRef = useRef(onBoardLoaded);

  useEffect(() => {
    boardLoadedRef.current = onBoardLoaded;
  }, [onBoardLoaded]);

  const applyBoard = useCallback((next: Board) => {
    setBoard(next);
    boardLoadedRef.current?.(next);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await translationTaskApi.list({ sourceType, sourceId, chapterId });
      applyBoard(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [applyBoard, chapterId, sourceId, sourceType]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!board?.summary.is_running) return;
    const timer = window.setTimeout(() => {
      void translationTaskApi
        .list({ sourceType, sourceId, chapterId })
        .then((next) => {
          applyBoard(next);
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [applyBoard, board, chapterId, sourceId, sourceType]);

  const handlePlanAndRun = async () => {
    setRunning(true);
    setError(null);
    try {
      if (sourceType && sourceId) {
        await translationTaskApi.plan(sourceType, sourceId);
      }
      await translationTaskApi.stream({
        sourceType,
        sourceId,
        chapterId,
        limit: compact ? 4 : 8,
        onEvent: (event) => {
          if (event.board) applyBoard(event.board);
          if (event.type === "group_translated" && event.task) {
            onGroupTranslated?.(event.task);
          }
        },
      });
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

  const statusIcon = (status: string) => {
    if (status === "completed") return <CheckCircle2 className="size-3.5 text-emerald-600" />;
    if (status === "running") return <Loader2 className="size-3.5 animate-spin text-blue-600" />;
    if (status === "failed") return <XCircle className="size-3.5 text-red-600" />;
    return <Clock className="size-3.5 text-amber-600" />;
  };

  const visibleTasks = useMemo(() => board?.tasks.slice(0, compact ? 8 : 100) ?? [], [board, compact]);
  const summary = board?.summary;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ListChecks className="size-4" />
          {t("Translation Tasks")}
          {summary?.is_running && <Loader2 className="size-3.5 animate-spin text-blue-600" />}
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
            onClick={() => void handleRetryFailed()}
            disabled={running || !summary?.filtered_failed}
            className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs disabled:opacity-50"
          >
            <RefreshCw className="size-3.5" />
            {t("Retry failed")}
          </button>
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
