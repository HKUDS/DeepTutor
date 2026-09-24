"use client";

import { ListChecks, Loader2, Sparkles, Square, Volume2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useReadingActions } from "@/components/reading/reading-actions-context";

const READ_ALOUD_KEY = "read_aloud:read";

/**
 * Read-aloud as one header toggle: speaker to start, square to stop.
 *
 * It used to be a chip in the action strip that, once pressed, grew a second
 * "Reading aloud ■" band above the page — two rows of chrome for one on/off
 * state. Younger learners keep the big button in their own toolbar, so this
 * one steps aside for them rather than offering the same thing twice.
 */
export function ReadAloudButton({ disabled }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const shared = useReadingActions();
  const entry = shared?.actions.find((row) => row.key === READ_ALOUD_KEY);
  if (!shared || !entry || shared.ageMode !== "default") return null;

  const busy = shared.busyKey === READ_ALOUD_KEY;
  const label = shared.speaking
    ? t("Stop reading aloud")
    : t("Read this page aloud");
  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={() =>
        shared.speaking ? shared.stopSpeaking() : void shared.run(entry)
      }
      aria-label={label}
      aria-pressed={shared.speaking}
      title={label}
      className={`flex size-7 shrink-0 items-center justify-center rounded-md transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-40 ${
        shared.speaking
          ? "text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {busy ? (
        <Loader2 size={14} className="animate-spin" />
      ) : shared.speaking ? (
        <Square size={11} fill="currentColor" />
      ) : (
        <Volume2 size={14} />
      )}
    </button>
  );
}

/**
 * Actions on the page in view, as icons on the workspace bar beside
 * read-aloud. They used to sit behind a sparkle menu in the companion's own
 * header — one entry, one level down, on a second bar.
 *
 * "Quiz me" is a quiz turn in the reading conversation (`onQuiz`); anything
 * else here is an installed extension, whose answer lands as a card.
 */
export function PageToolButtons({
  disabled,
  onQuiz,
}: {
  disabled?: boolean;
  onQuiz: () => void;
}) {
  const { t } = useTranslation();
  const shared = useReadingActions();
  if (!shared || shared.ageMode !== "default") return null;
  const buttonClass =
    "flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={onQuiz}
        aria-label={t("Quiz me on this page")}
        title={t("Quiz me on this page")}
        className={buttonClass}
      >
        <ListChecks size={14} />
      </button>
      {shared.actions
        .filter(
          (entry) => !entry.needsSelection && entry.key !== READ_ALOUD_KEY,
        )
        .map((entry) => {
          const busy = shared.busyKey === entry.key;
          return (
            <button
              key={entry.key}
              type="button"
              disabled={disabled || busy}
              onClick={() => void shared.run(entry)}
              aria-label={entry.label}
              title={entry.label}
              className={buttonClass}
            >
              {busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
            </button>
          );
        })}
    </>
  );
}
