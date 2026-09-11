"use client";

import { useMemo } from "react";

import type { ContextBudget } from "@/components/chat/home/ContextBudgetChip";
import type { MessageItem } from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";

/**
 * The context-window readout for a composer chip.
 *
 * The measurement rides on a turn's closing `result` event, so this walks the
 * transcript newest-first and takes the newest turn that was actually
 * measured. That order is what keeps the number steady while a new turn
 * streams: the in-flight assistant message has no result event yet, the walk
 * falls through to the last completed turn, and the chip flips exactly once —
 * when the new measurement lands.
 *
 * Older backends emit no budget at all, so "absent" is a normal answer rather
 * than an error; the chip simply does not render.
 *
 * It lives here rather than inside the main chat workspace because two
 * surfaces now show the same chip over the same kind of transcript, and a
 * second copy of this walk would be a second definition of "how full is the
 * window" — the sort that drifts and then disagrees on screen.
 */
export function readContextBudget(
  events: StreamEvent[] | undefined,
): ContextBudget | null {
  if (!events) return null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.type !== "result") continue;
    const meta = ev.metadata?.metadata as Record<string, unknown> | undefined;
    const budget = meta?.context_budget as ContextBudget | undefined;
    if (
      budget &&
      typeof budget.window === "number" &&
      typeof budget.used_tokens === "number" &&
      Array.isArray(budget.segments)
    ) {
      return budget;
    }
  }
  return null;
}

export function useContextBudget(
  messages: readonly MessageItem[],
): ContextBudget | null {
  return useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const message = messages[i];
      if (message.role !== "assistant") continue;
      const budget = readContextBudget(message.events);
      if (budget) return budget;
    }
    return null;
  }, [messages]);
}
