/**
 * Tiny app-wide notification pub-sub. A single ToastViewport (mounted in
 * the workspace layout) subscribes and renders any toast emitted by
 * `notify()`.
 *
 * Why pub-sub instead of a context: emitters can be outside React (WS
 * handlers, fetch wrappers, plain utility code). Coupling a context would
 * force every non-React caller into a hook-friendly shape it doesn't need.
 * Pub-sub lets us emit from anywhere and render in one place.
 *
 * Replaces three hand-rolled toasts that lived inside individual pages
 * (agents, settings, MemorySection) — each with their own state and
 * styling. New code should call `notify()` rather than start a fourth.
 */

export type NotificationTone = "info" | "success" | "error";

export interface Notification {
  id: number;
  message: string;
  tone: NotificationTone;
  durationMs: number;
}

type Listener = (n: Notification) => void;

const listeners = new Set<Listener>();
let counter = 0;

export function notify(
  message: string,
  options: { tone?: NotificationTone; durationMs?: number } = {},
): void {
  if (!message) return;
  counter += 1;
  const notification: Notification = {
    id: counter,
    message,
    tone: options.tone ?? "info",
    durationMs: options.durationMs ?? 4000,
  };
  for (const listener of Array.from(listeners)) {
    try {
      listener(notification);
    } catch {
      /* a misbehaving listener should not break siblings */
    }
  }
}

export function subscribeNotifications(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
