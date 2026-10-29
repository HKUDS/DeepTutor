"use client";

/**
 * Messages sent while the turn runs, in the box they were sent from.
 *
 * Each waits its turn: plain words are offered to the running turn, which
 * reads them after the step in flight; the rest go as the next turn once
 * this one ends. Either can be taken back until it is read.
 */

import { CornerDownRight, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { QueuedMessage } from "@/features/chat/ChatStateAdapter";
import Tooltip from "@/shared/ui/Tooltip";

export default function QueuedMessages({
  messages,
  isStreaming,
  onWithdraw,
}: {
  messages: QueuedMessage[];
  isStreaming: boolean;
  onWithdraw: (id: string) => void;
}) {
  const { t } = useTranslation();
  if (!messages.length) return null;
  return (
    <ul
      aria-label={t("Queued messages")}
      className="flex flex-col gap-0.5 px-4 pt-3"
    >
      {messages.map((message) => (
        <li
          key={message.id}
          className="group flex items-start gap-2 text-[12.5px] leading-relaxed"
        >
          <CornerDownRight
            size={13}
            strokeWidth={1.8}
            aria-hidden="true"
            className="mt-[3px] shrink-0 text-[var(--muted-foreground)]"
          />
          <span className="line-clamp-2 min-w-0 flex-1 whitespace-pre-line text-[var(--foreground)]">
            {message.content}
          </span>
          <span className="mt-px shrink-0 text-[11px] text-[var(--muted-foreground)]">
            {!isStreaming
              ? t("Sending…")
              : message.steerable
                ? t("Read after this step")
                : t("Sent after this reply")}
          </span>
          <Tooltip label={t("Remove from queue")}>
            <button
              type="button"
              aria-label={t("Remove from queue")}
              onClick={() => onWithdraw(message.id)}
              className="-mr-1 inline-flex size-5 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-60 transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] hover:opacity-100 group-hover:opacity-100"
            >
              <X size={12} />
            </button>
          </Tooltip>
        </li>
      ))}
    </ul>
  );
}
