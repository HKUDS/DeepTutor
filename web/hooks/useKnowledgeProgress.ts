"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, wsUrl } from "@/lib/api";
import { taskFailureMessage, type ProgressInfo } from "@/lib/knowledge-helpers";

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
): TaskState {
  const taskId = expectedTaskId || progress.task_id;
  if (taskId && current.taskId !== taskId) return current;
  const logs = appendTaskLog(current.logs, progress.message);
  if (progress.stage === "completed") {
    return { ...current, logs, executing: false, error: null };
  }
  if (progress.stage === "error") {
    return {
      ...current,
      logs,
      executing: false,
      error: progress.error || progress.message || "Task failed",
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

  const closeSocket = useCallback((kbName: string) => {
    socketsRef.current[kbName]?.close();
    delete socketsRef.current[kbName];
  }, []);

  const closeSource = useCallback((kbName: string) => {
    sourcesRef.current[kbName]?.close();
    delete sourcesRef.current[kbName];
  }, []);

  const closeAll = useCallback(() => {
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
      closeSocket(kbName);
      const query = expectedTaskId
        ? `?task_id=${encodeURIComponent(expectedTaskId)}`
        : "";
      const socket = new WebSocket(
        wsUrl(
          `/api/v1/knowledge/${encodeURIComponent(kbName)}/progress/ws${query}`,
        ),
      );
      socketsRef.current[kbName] = socket;

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

      socket.onerror = () => closeSocket(kbName);
      socket.onclose = () => {
        delete socketsRef.current[kbName];
      };
    },
    [closeSocket, closeSource, setProgress],
  );

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
        apiUrl(`/api/v1/knowledge/tasks/${encodeURIComponent(taskId)}/stream`),
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
    [closeSource, setProgress],
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
      closeSource(kbName);
      setTasksByKb((prev) => {
        if (!(kbName in prev)) return prev;
        const next = { ...prev };
        delete next[kbName];
        return next;
      });
    },
    [closeSource],
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
