"use client";

/**
 * FollowupChips — the one-click reactions offered under the latest answer.
 *
 * A learner who cannot say *why* an answer did not fit can still say what they
 * need: "more simply", "define the terms", "add cause and fix". Each chip sends
 * its prompt as the learner's own next message. The set is chosen server-side
 * (see `deeptutor/services/chat_followups.py`); this only renders it, showing a
 * few at a time with a reroll when more are offered.
 */

import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";

import type { FollowupSuggestion } from "@/lib/session-api";

/** How many chips are on screen at once. */
const VISIBLE = 4;

const CHIP =
  "inline-flex items-center rounded-full border border-[color-mix(in_srgb,var(--border)_70%,transparent)] px-3 py-1.5 text-[12.5px] text-[var(--muted-foreground)] transition-colors hover:border-[color-mix(in_srgb,var(--primary)_35%,transparent)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

export default function FollowupChips({
  suggestions,
  offset,
  onCycle,
  onPick,
}: {
  suggestions: FollowupSuggestion[];
  /** First visible chip; owned by the parent so it resets per turn. */
  offset: number;
  onCycle: () => void;
  onPick: (prompt: string) => void;
}) {
  const { t } = useTranslation();
  if (suggestions.length === 0) return null;

  const rows =
    suggestions.length <= VISIBLE
      ? suggestions
      : Array.from(
          { length: VISIBLE },
          (_, index) => suggestions[(offset + index) % suggestions.length],
        );

  return (
    <div className="flex flex-wrap items-center gap-2">
      {rows.map((suggestion) => (
        <button
          key={`${suggestion.id}:${offset}`}
          type="button"
          className={CHIP}
          title={suggestion.prompt}
          onClick={() => onPick(suggestion.prompt)}
          disabled={!suggestion.prompt}
        >
          {suggestion.label}
        </button>
      ))}
      {suggestions.length > VISIBLE ? (
        <button
          type="button"
          onClick={onCycle}
          aria-label={t("More suggestions")}
          className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:text-[var(--foreground)]"
        >
          <RefreshCw size={13} strokeWidth={1.9} />
        </button>
      ) : null}
    </div>
  );
}
