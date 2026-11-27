"use client";

/**
 * The Little Tutor entry point under a message.
 *
 * A thread records the message it was opened from in
 * ``preferences.tutor_source_message_id``. This renders one quiet line there —
 * ``Little Tutor ×2`` — and opens a popover listing those threads: each row
 * focuses the existing tab, and deleting one closes it for good.
 *
 * Bare side chats and threads created before the attribution existed have no
 * source message, so they never reach this component; the viewer's own
 * launcher still lists them.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { MessagesSquare, Trash2, Unlink } from "lucide-react";

import type { SessionSummary } from "@/lib/session-api";
import { placeMenu } from "@/lib/floating-menu";
import { formatRelativeTime } from "@/lib/relative-time";
import { displaySessionTitle } from "@/lib/session-title";

const POPOVER_WIDTH = 304;

interface PopoverPosition {
  left: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
}

export interface MessageThreadMarkerProps {
  threads: SessionSummary[];
  /** User bubbles align right; assistant bubbles align left. */
  align?: "left" | "right";
  onOpen: (thread: SessionSummary) => void;
  onDelete: (thread: SessionSummary) => Promise<void>;
  /** Remove the thread from this message without deleting the conversation. */
  onDetach?: (thread: SessionSummary) => Promise<void>;
}

export default function MessageThreadMarker({
  threads,
  align = "left",
  onOpen,
  onDelete,
  onDetach,
}: MessageThreadMarkerProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<PopoverPosition | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [detaching, setDetaching] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const close = useCallback((restoreFocus = false) => {
    setOpen(false);
    setPosition(null);
    setConfirming(null);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  const toggle = useCallback(() => {
    if (open) {
      close();
      return;
    }
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const placement = placeMenu(rect, POPOVER_WIDTH);
    setPosition({
      left: placement.left,
      // ``placeMenu`` reports the anchored edge; above the button we must hang
      // the popover from its bottom instead of starting it at the anchor top.
      ...(placement.openUpward
        ? { bottom: window.innerHeight - rect.top + 8 }
        : { top: rect.bottom + 8 }),
      maxHeight: placement.maxHeight,
    });
    setOpen(true);
  }, [close, open]);

  // A popover that outlives its threads (the last one was deleted) has nothing
  // left to say.
  useEffect(() => {
    if (open && threads.length === 0) close();
  }, [close, open, threads.length]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (popoverRef.current?.contains(target) || triggerRef.current?.contains(target)) {
        return;
      }
      close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close(true);
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && popoverRef.current?.contains(event.target)) {
        return;
      }
      close();
    };
    const onResize = () => close();
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [close, open]);

  if (threads.length === 0) return null;

  const openThread = (thread: SessionSummary) => {
    close();
    onOpen(thread);
  };

  const deleteThread = async (thread: SessionSummary) => {
    if (deleting) return;
    setDeleting(thread.session_id);
    try {
      await onDelete(thread);
      setConfirming(null);
    } catch {
      // The page that owns the deletion says what went wrong; return the row
      // to its normal state so the learner can try again.
      setConfirming(null);
    } finally {
      setDeleting(null);
    }
  };

  const detachThread = async (thread: SessionSummary) => {
    if (!onDetach || detaching) return;
    setDetaching(thread.session_id);
    try {
      await onDetach(thread);
    } catch {
      // The page that owns the detach explains the failure; the row stays.
    } finally {
      setDetaching(null);
    }
  };

  return (
    <div
      className={`mt-1 flex ${align === "right" ? "justify-end pr-1" : "justify-start"}`}
      data-message-thread-marker={threads.length}
    >
      <button
        ref={triggerRef}
        type="button"
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t("Tutor threads on this message")}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/45 hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--ring)]"
      >
        <MessagesSquare size={11} strokeWidth={1.8} aria-hidden="true" />
        {t("Little Tutor ×{{count}}", { count: threads.length })}
      </button>
      {open && position
        ? createPortal(
            <div
              ref={popoverRef}
              role="dialog"
              aria-label={t("Tutor threads on this message")}
              style={{
                position: "fixed",
                left: position.left,
                ...(position.top !== undefined ? { top: position.top } : {}),
                ...(position.bottom !== undefined ? { bottom: position.bottom } : {}),
                width: POPOVER_WIDTH,
                maxHeight: position.maxHeight,
              }}
              className="z-[70] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-1.5 shadow-lg"
            >
              <p className="px-2 pb-1 pt-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">
                {t("Tutor threads on this message")}
              </p>
              <div className="flex flex-col">
                {threads.map((thread) => (
                  <ThreadRow
                    key={thread.session_id}
                    thread={thread}
                    timeLabel={
                      thread.status === "running"
                        ? t("Running…")
                        : thread.status === "failed"
                          ? t("Failed")
                          : thread.updated_at
                            ? formatRelativeTime(thread.updated_at, i18n.language)
                            : ""
                    }
                    confirming={confirming === thread.session_id}
                    deleting={deleting === thread.session_id}
                    deleteDisabled={
                      deleting !== null || detaching !== null || thread.status === "running"
                    }
                    detaching={detaching === thread.session_id}
                    canDetach={Boolean(onDetach)}
                    onOpen={() => openThread(thread)}
                    onDetach={() => void detachThread(thread)}
                    onAskDelete={() => setConfirming(thread.session_id)}
                    onCancelDelete={() => setConfirming(null)}
                    onConfirmDelete={() => void deleteThread(thread)}
                  />
                ))}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function ThreadRow({
  thread,
  timeLabel,
  confirming,
  deleting,
  detaching,
  deleteDisabled,
  canDetach,
  onOpen,
  onDetach,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  thread: SessionSummary;
  timeLabel: string;
  confirming: boolean;
  deleting: boolean;
  detaching: boolean;
  deleteDisabled: boolean;
  canDetach: boolean;
  onOpen: () => void;
  onDetach: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const { t } = useTranslation();
  const title = displaySessionTitle(thread.title, t("Side chat"));
  return (
    <div className="group/thread flex items-start rounded-lg transition-colors hover:bg-[var(--secondary)]">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`${t("Open tutor thread")}: ${title}`}
        className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-lg px-2 py-1.5 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--ring)]"
      >
        <span className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
          {title}
        </span>
        {timeLabel ? (
          <span
            className={`text-[11px] ${
              thread.status === "running"
                ? "text-[var(--primary)]"
                : thread.status === "failed"
                  ? "text-[var(--destructive)]"
                  : "text-[var(--muted-foreground)]"
            }`}
          >
            {timeLabel}
          </span>
        ) : null}
      </button>
      {confirming ? (
        <span className="flex items-center gap-1 pr-1 pt-1.5">
          <button
            type="button"
            disabled={deleting}
            onClick={onConfirmDelete}
            className="rounded-md bg-[var(--destructive)] px-1.5 py-0.5 text-[11px] font-medium text-[var(--destructive-foreground)] disabled:opacity-50"
          >
            {t("Delete")}
          </button>
          <button
            type="button"
            disabled={deleting}
            onClick={onCancelDelete}
            className="rounded-md px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 disabled:opacity-50"
          >
            {t("Cancel")}
          </button>
        </span>
      ) : (
        <span className="flex shrink-0 items-center">
          {canDetach ? (
            <button
              type="button"
              disabled={detaching || deleteDisabled}
              onClick={onDetach}
              aria-label={t("Detach from this message")}
              className="mr-0.5 mt-1.5 flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition-opacity hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)] focus-visible:opacity-100 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 group-hover/thread:opacity-100"
            >
              <Unlink size={12} strokeWidth={1.7} />
            </button>
          ) : null}
          <button
            type="button"
            disabled={deleteDisabled}
            onClick={onAskDelete}
            aria-label={t("Delete tutor thread")}
            className="mr-1 mt-1.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition-opacity hover:bg-[var(--muted)]/50 hover:text-[var(--destructive)] focus-visible:opacity-100 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-30 group-hover/thread:opacity-100"
          >
            <Trash2 size={12} strokeWidth={1.7} />
          </button>
        </span>
      )}
    </div>
  );
}
