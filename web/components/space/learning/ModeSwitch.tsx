"use client";

import { useTranslation } from "react-i18next";

import {
  MASTERY_MODES,
  MASTERY_MODE_LABELS,
  type MasteryMode,
} from "@/lib/mastery-mode";

/**
 * The three things a mastery conversation can be doing, with the live one marked.
 *
 * All three are shown, not just the current one. The mode decides which tools
 * the tutor may use, so it is the answer to "why can it not just fix that for
 * me" — and a learner can only ask that question if they can see the other two
 * modes exist. Naming only the current one made the mode look like a status
 * readout instead of a control.
 *
 * The mark is a ring that fills, not an orb. An orb means *DeepTutor is
 * working*; there are two on this screen already (the header's activity line
 * and every assistant turn), and a third one that meant "you are here" would
 * be the same glyph saying two different things. A ring is the same visual
 * family — small, round, drawn in the product's ink — while reading as a
 * position rather than as motion.
 */
export function ModeSwitch({
  mode,
  onSelect,
  disabled = false,
  className = "",
}: {
  mode: MasteryMode;
  onSelect: (next: MasteryMode) => void;
  /** A turn is live: its tool surface was decided when it started. */
  disabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <div
      role="group"
      aria-label={t("Conversation mode")}
      className={`flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/60 p-0.5 ${className}`}
    >
      {MASTERY_MODES.map((candidate) => {
        const active = candidate === mode;
        return (
          <button
            key={candidate}
            type="button"
            onClick={() => !active && onSelect(candidate)}
            disabled={disabled || active}
            aria-pressed={active}
            // Why it is not clickable right now, rather than a dead control.
            title={
              disabled
                ? t("Wait for the tutor to finish before changing mode")
                : undefined
            }
            className={`flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium transition ${
              active
                ? "bg-[var(--background)] text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:hover:text-[var(--muted-foreground)]"
            } disabled:cursor-default`}
          >
            <span
              aria-hidden="true"
              className={`h-[7px] w-[7px] rounded-full border transition-colors ${
                active
                  ? "border-[var(--primary)] bg-[var(--primary)]"
                  : "border-[var(--muted-foreground)]/45"
              }`}
            />
            {t(MASTERY_MODE_LABELS[candidate])}
          </button>
        );
      })}
    </div>
  );
}
