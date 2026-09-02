"use client";

import { browserStorage } from "@/shared/storage";

import { useCallback, useEffect, useState } from "react";
import type { TaskKind } from "@/hooks/useKnowledgeProgress";

export interface HistoryEntry {
  id: string;
  taskId: string;
  kind: TaskKind;
  label: string;
  status: "completed" | "error";
  startedAt: number;
  completedAt: number;
  fileCount?: number;
  error?: string | null;
  /** Tail of log lines (capped) for retrospective inspection. */
  logTail: string[];
}

const STORAGE_KEY = "knowledge:history:v1";
const MAX_PER_KB = 20;
const MAX_LOG_LINES = 80;
const MAX_LOG_CHARS = 8 * 1024;

interface HistoryStore {
  byKb: Record<string, HistoryEntry[]>;
}

function readStore(): HistoryStore {
  if (typeof window === "undefined") return { byKb: {} };
  try {
    const raw = browserStorage.readRaw("local", STORAGE_KEY);
    if (!raw) return { byKb: {} };
    const parsed = JSON.parse(raw) as HistoryStore;
    if (parsed && typeof parsed === "object" && parsed.byKb) {
      return { byKb: parsed.byKb };
    }
  } catch {
    // corrupted or unavailable — fall through
  }
  return { byKb: {} };
}

function writeStore(store: HistoryStore) {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw("local", STORAGE_KEY, JSON.stringify(store));
  } catch {
    // quota exceeded; ignore
  }
}

function trimLogs(logs: string[]): string[] {
  const tail = logs.slice(-MAX_LOG_LINES);
  // Also bound total size in case lines are huge.
  let total = 0;
  const out: string[] = [];
  for (let i = tail.length - 1; i >= 0; i--) {
    const line = tail[i];
    total += line.length + 1;
    if (total > MAX_LOG_CHARS) break;
    out.unshift(line);
  }
  return out;
}

export function useKnowledgeHistory() {
  const [store, setStore] = useState<HistoryStore>({ byKb: {} });

  // Hydrate from localStorage on mount. The initial render must be empty so
  // SSR and the first client render match — only after hydration can we read
  // browser storage.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStore(readStore());
  }, []);

  // Cross-tab sync: refresh when storage changes elsewhere.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      setStore(readStore());
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const append = useCallback(
    (kbName: string, entry: Omit<HistoryEntry, "id">) => {
      setStore((prev) => {
        const existing = prev.byKb[kbName] ?? [];
        // Dedupe by taskId — final progress events sometimes fire twice.
        if (existing.some((e) => e.taskId === entry.taskId)) {
          return prev;
        }
        const next: HistoryEntry = {
          ...entry,
          logTail: trimLogs(entry.logTail || []),
          id: `${entry.taskId}:${entry.completedAt}`,
        };
        const updated = [next, ...existing].slice(0, MAX_PER_KB);
        const newStore = {
          byKb: { ...prev.byKb, [kbName]: updated },
        };
        writeStore(newStore);
        return newStore;
      });
    },
    [],
  );

  const renameKb = useCallback((from: string, to: string) => {
    setStore((prev) => {
      if (!(from in prev.byKb)) return prev;
      const newByKb = { ...prev.byKb };
      newByKb[to] = newByKb[from];
      delete newByKb[from];
      const next = { byKb: newByKb };
      writeStore(next);
      return next;
    });
  }, []);

  const removeKb = useCallback((kbName: string) => {
    setStore((prev) => {
      if (!(kbName in prev.byKb)) return prev;
      const newByKb = { ...prev.byKb };
      delete newByKb[kbName];
      const next = { byKb: newByKb };
      writeStore(next);
      return next;
    });
  }, []);

  const clearKb = useCallback((kbName: string) => removeKb(kbName), [removeKb]);

  return {
    historyByKb: store.byKb,
    append,
    renameKb,
    removeKb,
    clearKb,
  };
}

export type UseKnowledgeHistoryReturn = ReturnType<typeof useKnowledgeHistory>;
