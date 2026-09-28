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
