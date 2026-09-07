"use client";

/**
 * The answer card for a mastery question.
 *
 * Its sibling `AskUserOptions` exists to unblock a decision: it shows a label
 * and, under it, whatever else the model wanted to say about that choice. A
 * mastery question does not fit that — its options *are* bodies of text, and
 * they are numbered — so the generic card printed the letter twice, once as
 * the badge and once as the label, above the answer it was labelling.
 *
 * The look follows the rule the mastery surface already set for itself (see
 * `mastery-theme.css`): state is carried by *form*, not by a skin. So there is
 * no boxed panel, no filled rows and no coloured verdict banner — a question
 * is a rule down the left margin, a prompt, and lines of text you can pick.
 * The rule is what changes: neutral while it is the learner's move, primary or
 * destructive once the gate has ruled. It should read like a question on a
 * page, not like a form to fill in.
 */

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCardSubmission } from "@/hooks/use-card-submission";
import { REPLY_NOT_DELIVERED } from "@/lib/ask-user-state";
import { decodeEscapedUnicodeForDisplay } from "@/lib/markdown-display";
import type {
  MasteryGradeResult,
  MasteryQuestion,
} from "@/lib/mastery-question";

/** Difficulty is a three-point scale; anything else is not shown. */
const DIFFICULTY_LABELS: Record<string, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

type OptionState = "idle" | "picked" | "correct" | "wrong";

function OptionRow({
  option,
  index,
  state,
  disabled,
  onPick,
}: {
  option: { label: string; body: string };
  index: number;
  state: OptionState;
  disabled: boolean;
  onPick: () => void;
}) {
  const letter = option.label || String.fromCharCode(65 + index);
  // The marker carries the state on its own: outline → filled, in whatever
  // colour the verdict gives it. The row never becomes a coloured block.
  const marker =
    state === "correct" || state === "picked"
      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
      : state === "wrong"
        ? "border-[var(--destructive)] bg-[var(--destructive)] text-[var(--destructive-foreground)]"
        : "border-[var(--border)] text-[var(--muted-foreground)] group-hover:border-[color-mix(in_srgb,var(--foreground)_35%,transparent)] group-hover:text-[var(--foreground)]";
  const body =
    state === "wrong"
      ? "text-[var(--muted-foreground)]"
      : "text-[var(--foreground)]";
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={disabled}
      className={
        "group -mx-2 flex items-baseline gap-3 rounded-lg px-2 py-1.5 text-left transition-colors " +
        (disabled
          ? "cursor-default"
          : "hover:bg-[color-mix(in_srgb,var(--foreground)_3.5%,transparent)]")
      }
    >
      <span
        className={
          "relative top-px flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border text-[10.5px] font-semibold transition-colors " +
          marker
        }
      >
        {letter}
      </span>
      {/* The body is the option. It is never printed beside its own letter. */}
      <span className={"min-w-0 flex-1 text-[13.5px] leading-relaxed " + body}>
        {decodeEscapedUnicodeForDisplay(option.body)}
      </span>
    </button>
  );
}

export const MasteryQuestionCard = memo(function MasteryQuestionCard({
  question,
  grade,
  answered,
  skipped,
  submittedAnswer,
  onSubmit,
  onSkip,
}: {
  question: MasteryQuestion;
  /** The gate's ruling, once it has been made. */
  grade: MasteryGradeResult | null;
  /** The learner has already answered this card (this turn or an earlier one). */
  answered: boolean;
  /** The learner dropped this question; the engine closed it ungraded. */
  skipped?: boolean;
  /** What they answered, when the transcript knows it. */
  submittedAnswer: string;
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void | boolean | Promise<void | boolean>;
  /** Drop this question and let the tutor move on. Absent where the surface
   *  cannot start a turn of its own, which hides the control entirely. */
  onSkip?: (questionId: string) => void | boolean | Promise<void | boolean>;
}) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<string>("");
  const [skipping, setSkipping] = useState(false);
  const [freeText, setFreeText] = useState("");
  const [freeSelected, setFreeSelected] = useState(false);
  const { sending, failed: sendFailed, submit } = useCardSubmission(onSubmit);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (freeSelected) textareaRef.current?.focus();
  }, [freeSelected]);

  const hasChoices = question.options.length > 0;
  const answer = freeSelected ? freeText.trim() : picked;
  // Skipping settles the card exactly as answering does: the engine closed the
  // question, so there is nothing left on it to send.
  const settled = answered || skipped === true;
  const locked = settled || sending || skipping;

  const handleSkip = useCallback(() => {
    if (locked || !onSkip) return;
    setSkipping(true);
    void Promise.resolve(onSkip(question.questionId)).then((accepted) => {
      // Same rule as an answer: only an explicit refusal reopens the card.
      if (accepted === false) setSkipping(false);
    });
  }, [locked, onSkip, question.questionId]);

  const handleSubmit = useCallback(() => {
    if (locked || !answer) return;
    void submit({
      text: answer,
      answers: [{ questionId: question.questionId, text: answer }],
    });
  }, [answer, locked, submit, question.questionId]);

  // Which answer to treat as the learner's, preferring what the graded record
  // committed over what this browser happens to remember.
  const learnerAnswer = grade?.learnerAnswer || submittedAnswer || answer;
  const difficultyLabel = DIFFICULTY_LABELS[question.difficulty] ?? "";
  const meta = [
    question.objectiveName,
    difficultyLabel ? t(difficultyLabel) : "",
    question.attempt > 1
      ? t("Attempt {{count}}", { count: question.attempt })
      : "",
  ].filter(Boolean);

  // The rule down the left margin is the whole status indicator.
  const rule = grade
    ? grade.isCorrect
      ? "border-[var(--primary)]"
      : "border-[var(--destructive)]"
    : skipped
      ? // Closed, but nothing was judged — a dashed rule says "set aside"
        // where a solid one would claim a verdict that was never made.
        "border-dashed border-[var(--border)]"
      : "border-[var(--border)]";

  const optionState = (option: { label: string }): OptionState => {
    if (grade) {
      if (option.label && option.label === grade.correctLabel) return "correct";
      if (option.label && option.label === learnerAnswer && !grade.isCorrect)
        return "wrong";
      return "idle";
    }
    if (settled) return option.label === learnerAnswer ? "picked" : "idle";
    return !freeSelected && option.label === picked ? "picked" : "idle";
  };

  return (
    <div className={"my-4 border-l-2 pl-4 transition-colors sm:pl-5 " + rule}>
      {meta.length > 0 ? (
        <div className="text-[11px] leading-5 text-[var(--muted-foreground)]">
          {meta.join(" · ")}
        </div>
      ) : null}

      <div className="mt-0.5 font-serif text-[15.5px] font-semibold leading-relaxed tracking-[-0.01em] text-[var(--foreground)]">
        {decodeEscapedUnicodeForDisplay(question.prompt)}
      </div>

      {hasChoices ? (
        <div className="mt-2.5 flex flex-col gap-0.5">
          {question.options.map((option, idx) => (
            <OptionRow
              key={`${option.label}-${idx}`}
              option={option}
              index={idx}
              state={optionState(option)}
              disabled={locked}
              onPick={() => {
                setFreeSelected(false);
                setPicked(option.label);
              }}
            />
          ))}
        </div>
      ) : null}

      {question.allowFreeText && !settled ? (
        <div className="mt-1.5">
          {freeSelected || !hasChoices ? (
            <textarea
              ref={textareaRef}
              value={freeText}
              onChange={(event) => setFreeText(event.target.value)}
              placeholder={t("Write your answer…")}
              rows={hasChoices ? 2 : 3}
              disabled={locked}
              className="w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2.5 py-2 text-[13.5px] leading-relaxed text-[var(--foreground)] outline-none transition-colors placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_75%,transparent)] focus:border-[color-mix(in_srgb,var(--foreground)_35%,transparent)] disabled:opacity-60"
            />
          ) : (
            <button
              type="button"
              onClick={() => setFreeSelected(true)}
              disabled={locked}
              className="-mx-2 flex items-baseline gap-3 rounded-lg px-2 py-1.5 text-left text-[13px] text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--foreground)_3.5%,transparent)] hover:text-[var(--foreground)] disabled:cursor-default"
            >
              <span className="relative top-px flex h-[19px] w-[19px] shrink-0 items-center justify-center rounded-full border border-dashed border-[var(--border)] text-[10.5px] font-semibold">
                +
              </span>
              {t("Answer in my own words")}
            </button>
          )}
        </div>
      ) : null}

      {/* The ruling, as prose under a hairline — not another coloured panel. */}
      {grade ? (
        <div className="mt-3 border-t border-[var(--border)] pt-2.5">
          <div className="text-[12.5px] leading-relaxed">
            <span
              className={
                "font-semibold " +
                (grade.isCorrect
                  ? "text-[var(--primary)]"
                  : "text-[var(--destructive)]")
              }
            >
              {grade.isCorrect ? t("Correct") : t("Not quite")}
            </span>
            {!grade.isCorrect && grade.correctLabel ? (
              <span className="text-[var(--foreground)]">
                {" · "}
                {t("Answer: {{label}}", { label: grade.correctLabel })}
              </span>
            ) : null}
          </div>
          {grade.explanation ? (
            <div className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {decodeEscapedUnicodeForDisplay(grade.explanation)}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Footer: only while the question is still the learner's move. */}
      {!settled ? (
        <div className="mt-3 flex items-center justify-between gap-3">
          <span
            className={
              "text-[11px] " +
              (sendFailed
                ? "text-[var(--destructive)]"
                : "text-[var(--muted-foreground)]")
            }
          >
            {sending
              ? t("Sending your answers…")
              : sendFailed
                ? t(REPLY_NOT_DELIVERED)
                : hasChoices
                  ? t("Pick the option you think is right.")
                  : t("Write your answer to continue.")}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            {/* Not a dead end: the engine holds one open question per path, so
                without this the tutor's next question is this same one again.
                Quiet, because skipping is the rarer move. */}
            {onSkip ? (
              <button
                type="button"
                onClick={handleSkip}
                disabled={locked}
                className="rounded-md px-2 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {skipping ? t("Skipping…") : t("Skip this one")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={handleSubmit}
              disabled={locked || !answer}
              className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("Submit")}
            </button>
          </div>
        </div>
      ) : skipped ? (
        <div className="mt-2.5 text-[11px] text-[var(--muted-foreground)]">
          {t("Skipped — no attempt was recorded for this question.")}
        </div>
      ) : !grade ? (
        <div className="mt-2.5 text-[11px] text-[var(--muted-foreground)]">
          {t("Answer submitted — your tutor is checking it.")}
        </div>
      ) : null}
    </div>
  );
});

export default MasteryQuestionCard;
