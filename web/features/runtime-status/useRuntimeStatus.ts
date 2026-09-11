"use client";

import { useSyncExternalStore } from "react";
import { fetchRuntimeStatus } from "./api";
import { runtimeHealth, type RuntimeStatusSnapshot } from "./model";

const listeners = new Set<() => void>();
const INITIAL: RuntimeStatusSnapshot = {
  data: null,
  health: "unavailable",
  error: null,
  loading: true,
  lastUpdated: null,
};
let snapshot = INITIAL;
let timer: ReturnType<typeof setTimeout> | null = null;
let request: Promise<void> | null = null;
let controller: AbortController | null = null;
let failures = 0;

function emit(next: RuntimeStatusSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

function visible(): boolean {
  return (
    typeof document === "undefined" || document.visibilityState === "visible"
  );
}

function clearTimer() {
  if (timer) clearTimeout(timer);
  timer = null;
}

function schedule() {
  clearTimer();
  if (!listeners.size || !visible()) return;
  const delay = failures
    ? Math.min(120_000, 5_000 * 2 ** Math.min(failures - 1, 5))
    : 30_000;
  timer = setTimeout(() => void refreshRuntimeStatus(), delay);
}

export function refreshRuntimeStatus(): Promise<void> {
  if (request) return request;
  controller = new AbortController();
  if (!snapshot.data) emit({ ...snapshot, loading: true, error: null });
  request = fetchRuntimeStatus(controller.signal)
    .then((data) => {
      failures = 0;
      emit({
        data,
        health: runtimeHealth(data),
        error: null,
        loading: false,
        lastUpdated: Date.now(),
      });
    })
    .catch((error: unknown) => {
      if (controller?.signal.aborted) return;
      failures += 1;
      emit({
        ...snapshot,
        health: snapshot.data ? runtimeHealth(snapshot.data) : "unavailable",
        error:
          error instanceof Error
            ? error.message
            : "Runtime status is unavailable",
        loading: false,
      });
    })
    .finally(() => {
      request = null;
      controller = null;
      schedule();
    });
  return request;
}

function handleVisibility() {
  if (visible()) void refreshRuntimeStatus();
  else {
    clearTimer();
    controller?.abort();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1 && typeof window !== "undefined") {
    window.addEventListener("focus", handleVisibility);
    document.addEventListener("visibilitychange", handleVisibility);
    void refreshRuntimeStatus();
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && typeof window !== "undefined") {
      clearTimer();
      controller?.abort();
      window.removeEventListener("focus", handleVisibility);
      document.removeEventListener("visibilitychange", handleVisibility);
    }
  };
}

export function useRuntimeStatus(): RuntimeStatusSnapshot & {
  refresh: () => Promise<void>;
} {
  const current = useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => INITIAL,
  );
  return { ...current, refresh: refreshRuntimeStatus };
}
