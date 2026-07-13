"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { subscribeNotifications, type Notification } from "@/lib/notifications";

/**
 * Renders the toast stack in the bottom-right. Mounted once at the
 * workspace layout level — every call to `notify()` from anywhere in the
 * app appears here.
 *
 * Each toast lives for its own `durationMs`, then auto-dismisses. Users
 * can also dismiss manually via the X button. The viewport itself is
 * `aria-live="polite"` so assistive tech announces new toasts as they
 * arrive, without barging in on whatever the user was reading.
 */
export default function ToastViewport() {
  const [toasts, setToasts] = useState<Notification[]>([]);

  useEffect(() => {
    return subscribeNotifications((toast) => {
      setToasts((prev) => [...prev, toast]);
      const timer = window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== toast.id));
      }, toast.durationMs);
      // No cleanup needed — listener stays alive for the component's life;
      // individual setTimeouts are GC'd after they fire.
      void timer;
    });
  }, []);

  const dismiss = (id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  if (toasts.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-6 right-6 z-[200] flex flex-col gap-2"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto flex max-w-sm items-start gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur-md ${toneClass(
            toast.tone,
          )}`}
        >
          <span className="flex-1 text-[13px] leading-relaxed">
            {toast.message}
          </span>
          <button
            type="button"
            onClick={() => dismiss(toast.id)}
            className="rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
            aria-label="Dismiss"
          >
            <X size={14} strokeWidth={1.8} />
          </button>
        </div>
      ))}
    </div>
  );
}

function toneClass(tone: Notification["tone"]): string {
  switch (tone) {
    case "error":
      return "border-[var(--destructive)]/30 bg-[var(--destructive)]/10 text-[var(--destructive)]";
    case "success":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    default:
      return "border-[var(--border)] bg-[var(--card)]/95 text-[var(--foreground)]";
  }
}
