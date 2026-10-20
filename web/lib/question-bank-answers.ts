/** Prefer the recorded assessment result over the legacy binary projection. */
export function questionResult(entry: { result?: string; is_correct: boolean }): string {
  return entry.result || (entry.is_correct ? "correct" : "incorrect");
}

export function questionResultBadge(entry: { result?: string; is_correct: boolean }): {
  label: string;
  className: string;
} {
  switch (questionResult(entry)) {
    case "partial":
      return { label: "Partially Correct", className: "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400" };
    case "ungraded":
      return { label: "Not Graded", className: "bg-[var(--muted)] text-[var(--muted-foreground)]" };
    case "correct":
      return { label: "Correct", className: "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400" };
    default:
      return { label: "Incorrect", className: "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400" };
  }
}

/** Fold letters and option text so choice matching is not whitespace-sensitive. */
export function foldedAnswer(value: string): string {
  return value.trim().replace(/\s+/g, " ").toUpperCase();
}

/**
 * Choice records store either the option letter (Book / Deep Question) or
 * the option text (Immersive Reading). Match both so a review card can mark
 * the learner's pick and the reference answer.
 */
export function optionIsAnswer(
  key: string,
  text: string,
  answer: string,
): boolean {
  const needle = foldedAnswer(answer);
  if (!needle) return false;
  const label = foldedAnswer(key);
  const body = foldedAnswer(text);
  if (needle === label || needle === body) return true;
  return Boolean(
    body &&
      (needle === `${label}. ${body}` || needle === `${label}) ${body}`),
  );
}
