export type NormalizedQuizQuestionType = "choice" | "written" | "coding";

const QUESTION_TYPE_ALIASES: Record<string, NormalizedQuizQuestionType> = {
  choice: "choice",
  multiple_choice: "choice",
  "multiple-choice": "choice",
  mcq: "choice",
  written: "written",
  open_ended: "written",
  "open-ended": "written",
  open_response: "written",
  "open-response": "written",
  short_answer: "written",
  "short-answer": "written",
  essay: "written",
  fill_in_blank: "written",
  "fill-in-the-blank": "written",
  coding: "coding",
  code: "coding",
  programming: "coding",
};

export function normalizeQuizQuestionType(
  value: unknown,
): NormalizedQuizQuestionType {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");
  return QUESTION_TYPE_ALIASES[normalized] || "written";
}

export function isChoiceQuizQuestion(value: unknown): boolean {
  return normalizeQuizQuestionType(value) === "choice";
}

export function resolveChoiceAnswerKey(
  correctAnswer: unknown,
  options: Record<string, string> | null | undefined,
): string {
  const correct = String(correctAnswer || "").trim();
  if (!correct || !options) return "";

  const directKey = correct.toUpperCase();
  if (directKey in options) {
    return directKey;
  }

  const normalizedAnswer = correct.toLowerCase();
  for (const [key, label] of Object.entries(options)) {
    if (
      normalizedAnswer ===
      String(label || "")
        .trim()
        .toLowerCase()
    ) {
      return key.toUpperCase();
    }
  }

  return directKey;
}
