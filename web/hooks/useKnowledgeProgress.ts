"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, wsUrl } from "@/lib/api";
import {
  progressMessage,
  taskFailureMessage,
  type ProgressInfo,
} from "@/lib/knowledge-helpers";
import { useTranslation } from "react-i18next";

export type TaskKind = "create" | "upload" | "reindex" | "retry";

export interface TaskState {
  taskId: string;
  kind: TaskKind;
  label: string;
  logs: string[];
  executing: boolean;
  error: string | null;
  errorCode?: string;
  retryable?: boolean;
}

export function appendTaskLog(logs: string[], message?: string): string[] {
  const line = String(message || "").trim();
  if (!line || logs.at(-1) === line) return logs;
  return [...logs, line];
}

export function taskStateAfterProgress(
  current: TaskState,
  expectedTaskId: string | undefined,
  progress: ProgressInfo,
  /** Defaults to the key itself, i.e. the untranslated English. */
  t: (key: string, options?: Record<string, unknown>) => string = (key) => key,
): TaskState {
  const taskId = expectedTaskId || progress.task_id;
  if (taskId && current.taskId !== taskId) return current;
  const logs = appendTaskLog(current.logs, progressMessage(progress, t));
  if (progress.stage === "completed") {
    return { ...current, logs, executing: false, error: null };
  }
  if (progress.stage === "error") {
    return {
      ...current,
      logs,
      executing: false,
      error: progress.error || progressMessage(progress, t) || "Task failed",
      errorCode: progress.error_code,
      retryable: progress.retryable,
    };
  }
  return logs === current.logs ? current : { ...current, logs };
}

interface UseKnowledgeProgressOptions {
  onComplete?: (kbName: string) => void;
  /**
   * Called once each task settles (success or failure) with the final
   * task state. Lets the parent persist a history record.
   */
  onTaskSettled?: (
    kbName: string,
    final: TaskState & { startedAt: number; completedAt: number },
  ) => void;
}

export function useKnowledgeProgress(options?: UseKnowledgeProgressOptions) {
  // Progress lines arrive as English templates plus values; this hook is the
  // first place that knows the viewer's language.
  const { t } = useTranslation();
  const onCompleteRef = useRef(options?.onComplete);
  const onTaskSettledRef = useRef(options?.onTaskSettled);
  useEffect(() => {
    onCompleteRef.current = options?.onComplete;
  }, [options?.onComplete]);
  useEffect(() => {
    onTaskSettledRef.current = options?.onTaskSettled;
  }, [options?.onTaskSettled]);

  const startedAtRef = useRef<Record<string, number>>({});

  const [progressByKb, setProgressByKb] = useState<
    Record<string, ProgressInfo>
  >({});
  const [tasksByKb, setTasksByKb] = useState<Record<string, TaskState>>({});

  const socketsRef = useRef<Record<string, WebSocket>>({});
  const sourcesRef = useRef<Record<string, EventSource>>({});
  const socketTargetsRef = useRef<
    Record<string, { taskId?: string; retry: number }>
  >({});
  const socketRetryTimersRef = useRef<
    Record<string, ReturnType<typeof setTimeout>>
  >({});
  const subscribeWsRef = useRef<
    ((kbName: string, expectedTaskId?: string) => void) | null
  >(null);

  const closeSocket = useCallback((kbName: string) => {
    delete socketTargetsRef.current[kbName];
    const retryTimer = socketRetryTimersRef.current[kbName];
    if (retryTimer) clearTimeout(retryTimer);
    delete socketRetryTimersRef.current[kbName];
    const socket = socketsRef.current[kbName];
    delete socketsRef.current[kbName];
    socket?.close();
  }, []);

  const closeSource = useCallback((kbName: string) => {
    sourcesRef.current[kbName]?.close();
    delete sourcesRef.current[kbName];
  }, []);

  const closeAll = useCallback(() => {
    Object.values(socketRetryTimersRef.current).forEach((timer) =>
      clearTimeout(timer),
    );
    socketRetryTimersRef.current = {};
    socketTargetsRef.current = {};
    Object.values(socketsRef.current).forEach((s) => s.close());
    socketsRef.current = {};
    Object.values(sourcesRef.current).forEach((s) => s.close());
    sourcesRef.current = {};
  }, []);

  const setProgress = useCallback((kbName: string, info: ProgressInfo) => {
    setProgressByKb((prev) => ({ ...prev, [kbName]: info }));
  }, []);

  const clearProgress = useCallback((kbName: string) => {
    setProgressByKb((prev) => {
      if (!(kbName in prev)) return prev;
      const next = { ...prev };
      delete next[kbName];
      return next;
    });
  }, []);

  const subscribeWs = useCallback(
    (kbName: string, expectedTaskId?: string) => {
      const previous = socketsRef.current[kbName];
      delete socketsRef.current[kbName];
      previous?.close();
      const retryTimer = socketRetryTimersRef.current[kbName];
      if (retryTimer) clearTimeout(retryTimer);
      delete socketRetryTimersRef.current[kbName];
      const existingTarget = socketTargetsRef.current[kbName];
      socketTargetsRef.current[kbName] = {
        taskId: expectedTaskId,
        retry:
          existingTarget && existingTarget.taskId === expectedTaskId
            ? existingTarget.retry
            : 0,
      };
      const query = expectedTaskId
        ? `?task_id=${encodeURIComponent(expectedTaskId)}`
        : "";
      const socket = new WebSocket(
        wsUrl(
          `/ws/knowledge-bases/${encodeURIComponent(kbName)}/progress${query}`,
        ),
      );
      socketsRef.current[kbName] = socket;

      socket.onopen = () => {
        const target = socketTargetsRef.current[kbName];
        if (target && target.taskId === expectedTaskId) target.retry = 0;
      };

      socket.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data) as {
            type?: string;
            data?: ProgressInfo;
          } & ProgressInfo;
          const progress: ProgressInfo =
            raw?.type === "progress" && raw.data ? raw.data : raw;
          if (!progress || typeof progress !== "object") return;
          if (
            expectedTaskId &&
            progress.task_id &&
            progress.task_id !== expectedTaskId
          ) {
            return;
          }
          setProgress(kbName, progress);
          const stage = progress.stage;
          const terminal = stage === "completed" || stage === "error";
          setTasksByKb((prev) => {
            const current = prev[kbName];
            if (!current) return prev;
            const finalState = taskStateAfterProgress(
              current,
              expectedTaskId,
              progress,
              t,
            );
            if (finalState === current) return prev;
            const startedAt =
              startedAtRef.current[`${kbName}:${current.taskId}`] ?? Date.now();
            if (terminal && current.executing) {
              delete startedAtRef.current[`${kbName}:${current.taskId}`];
              onTaskSettledRef.current?.(kbName, {
                ...finalState,
                status: finalState.error ? "error" : "completed",
                startedAt,
                completedAt: Date.now(),
              } as TaskState & {
                startedAt: number;
                completedAt: number;
                status: "error" | "completed";
              });
            }
            return { ...prev, [kbName]: finalState };
          });
          if (stage === "completed" || stage === "error") {
            closeSocket(kbName);
            closeSource(kbName);
            onCompleteRef.current?.(kbName);
          }
        } catch {
          // ignore malformed event
        }
      };

      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (socketsRef.current[kbName] === socket) {
          delete socketsRef.current[kbName];
        }
        const target = socketTargetsRef.current[kbName];
        if (!target || target.taskId !== expectedTaskId) return;
        const delay = Math.min(500 * 2 ** target.retry, 5000);
        target.retry += 1;
        socketRetryTimersRef.current[kbName] = setTimeout(() => {
          delete socketRetryTimersRef.current[kbName];
          const latest = socketTargetsRef.current[kbName];
          if (!latest || latest.taskId !== expectedTaskId) return;
          subscribeWsRef.current?.(kbName, expectedTaskId);
        }, delay);
      };
    },
    [closeSocket, closeSource, setProgress, t],
  );

  useEffect(() => {
    subscribeWsRef.current = subscribeWs;
    return () => {
      if (subscribeWsRef.current === subscribeWs) {
        subscribeWsRef.current = null;
      }
    };
  }, [subscribeWs]);

  const openTaskStream = useCallback(
    (
      kbName: string,
      taskId: string,
      kind: TaskKind,
      label: string,
      initialLogs: string[] = [],
    ) => {
      closeSource(kbName);
      startedAtRef.current[`${kbName}:${taskId}`] = Date.now();
      setTasksByKb((prev) => ({
        ...prev,
        [kbName]: {
          taskId,
          kind,
          label,
          logs: initialLogs,
          executing: true,
          error: null,
        },
      }));

      const source = new EventSource(
        apiUrl(
          `/api/knowledge-bases/tasks/${encodeURIComponent(taskId)}/stream`,
        ),
        { withCredentials: true },
      );
      sourcesRef.current[kbName] = source;

      let settled = false;

      source.addEventListener("process_log", (event) => {
        try {
          const payload = JSON.parse((event as MessageEvent).data) as {
            message?: string;
          };
          if (!payload.message) return;
          setTasksByKb((prev) => {
            const current = prev[kbName];
            if (!current || current.taskId !== taskId) return prev;
            return {
              ...prev,
              [kbName]: {
                ...current,
                logs: [...current.logs, payload.message!],
              },
            };
          });
        } catch {
          // ignore malformed process log
        }
      });

      source.addEventListener("progress", (event) => {
        try {
          const payload = JSON.parse(
            (event as MessageEvent).data,
          ) as ProgressInfo;
          setProgress(kbName, payload);
          // The progress bar reads `percent`; the log box reads `task.logs`.
          // Also surface the message so "Describing images: m/n" and
          // "Embedding batches: N/M" stream into the log box live (not only at
          // completion). Dedupe against the last line: process_log may already
          // have emitted the same message via _task_log.
          const line = progressMessage(payload, t);
          if (line) {
            setTasksByKb((prev) => {
              const current = prev[kbName];
              if (!current || current.taskId !== taskId) return prev;
              const logs = appendTaskLog(current.logs, line);
              if (logs === current.logs) return prev;
              return {
                ...prev,
                [kbName]: {
                  ...current,
                  logs,
                },
              };
            });
          }
        } catch {
          // ignore malformed progress
        }
      });

      source.addEventListener("complete", () => {
        settled = true;
        setTasksByKb((prev) => {
          const current = prev[kbName];
          if (!current || current.taskId !== taskId) return prev;
          if (!current.executing) return prev;
          const finalState = { ...current, executing: false };
          const startedAt =
            startedAtRef.current[`${kbName}:${taskId}`] ?? Date.now();
          delete startedAtRef.current[`${kbName}:${taskId}`];
          onTaskSettledRef.current?.(kbName, {
            ...finalState,
            status: "completed",
            startedAt,
            completedAt: Date.now(),
          } as TaskState & {
            startedAt: number;
            completedAt: number;
            status: "completed";
          });
          return { ...prev, [kbName]: finalState };
        });
        closeSource(kbName);
        onCompleteRef.current?.(kbName);
      });

      source.addEventListener("failed", (event) => {
        settled = true;
        let detail = "Task failed";
        let errorCode: string | undefined;
        let retryable: boolean | undefined;
        try {
          const payload = JSON.parse((event as MessageEvent).data) as {
            detail?: string;
            details?: string;
            error_code?: string;
            retryable?: boolean;
          };
          detail = taskFailureMessage(payload);
          errorCode = payload.error_code;
          retryable = payload.retryable;
        } catch {
          // ignore malformed failure event
        }
        setTasksByKb((prev) => {
          const current = prev[kbName];
          if (!current || current.taskId !== taskId) return prev;
          if (!current.executing) return prev;
          const finalState = {
            ...current,
            executing: false,
            error: detail,
            errorCode,
            retryable,
          };
          const startedAt =
            startedAtRef.current[`${kbName}:${taskId}`] ?? Date.now();
          delete startedAtRef.current[`${kbName}:${taskId}`];
          onTaskSettledRef.current?.(kbName, {
            ...finalState,
            startedAt,
            completedAt: Date.now(),
          } as TaskState & {
            startedAt: number;
            completedAt: number;
          });
          return { ...prev, [kbName]: finalState };
        });
        closeSource(kbName);
        onCompleteRef.current?.(kbName);
      });

      source.onerror = () => {
        if (settled) return;
        // EventSource reconnects automatically. Progress WebSocket remains the
        // authoritative terminal-state fallback while SSE reconnects.
      };
    },
    [closeSource, setProgress, t],
  );

  const startTask = useCallback(
    (params: {
      kbName: string;
      taskId: string;
      kind: TaskKind;
      label: string;
      seed?: ProgressInfo;
      initialLogs?: string[];
    }) => {
      const { kbName, taskId, kind, label, seed, initialLogs } = params;
      if (seed) setProgress(kbName, { ...seed, task_id: taskId });
      openTaskStream(kbName, taskId, kind, label, initialLogs);
      subscribeWs(kbName, taskId);
    },
    [openTaskStream, setProgress, subscribeWs],
  );

  const dismissTask = useCallback(
    (kbName: string) => {
      closeSocket(kbName);
      closeSource(kbName);
      setTasksByKb((prev) => {
        if (!(kbName in prev)) return prev;
        const next = { ...prev };
        delete next[kbName];
        return next;
      });
    },
    [closeSocket, closeSource],
  );

  const cleanupKb = useCallback(
    (kbName: string) => {
      closeSocket(kbName);
      closeSource(kbName);
      clearProgress(kbName);
      setTasksByKb((prev) => {
        if (!(kbName in prev)) return prev;
        const next = { ...prev };
        delete next[kbName];
        return next;
      });
    },
    [clearProgress, closeSocket, closeSource],
  );

  useEffect(() => {
    return () => {
      closeAll();
    };
  }, [closeAll]);

  return {
    progressByKb,
    tasksByKb,
    setProgress,
    clearProgress,
    subscribeWs,
    startTask,
    dismissTask,
    cleanupKb,
  };
}
