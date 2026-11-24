import type { AssessmentResult } from "@/lib/notebook-api";

/**
 * Structured verdict sent by the AI judge as its ``verdict`` frame (see
 * ``deeptutor/api/routers/quiz_judge.py``) and stored on the notebook entry.
 * The result vocabulary and confidence gate match the learning-path
 * semantic assessment, so ``ungraded`` never counts as right or wrong.
 */
export type QuizVerdictResult = "correct" | "partial" | "incorrect" | "ungraded";

export type QuizVerdictReason =
  | "missing_verdict"
  | "invalid_verdict"
  | "low_confidence"
  | "vision_unavailable";

export interface QuizVerdictStep {
  label: string;
  ok: boolean;
  comment: string;
}

export interface QuizVerdict {
  result: QuizVerdictResult;
  is_correct: boolean | null;
  final: boolean;
  confidence: number;
  feedback?: string;
  steps: QuizVerdictStep[];
  awarded_points?: number;
  max_points?: number;
  reason?: QuizVerdictReason;
}

const RESULTS = new Set<string>(["correct", "partial", "incorrect", "ungraded"]);
const REASONS = new Set<string>([
  "missing_verdict",
  "invalid_verdict",
  "low_confidence",
  "vision_unavailable",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate a verdict from the wire or the notebook; ``null`` if unusable. */
export function parseQuizVerdict(value: unknown): QuizVerdict | null {
  if (!isRecord(value) || typeof value.result !== "string") return null;
  if (!RESULTS.has(value.result)) return null;
  const result = value.result as QuizVerdictResult;
  const final = value.final === true && result !== "ungraded";
  const steps = Array.isArray(value.steps)
    ? value.steps.flatMap((step) =>
        isRecord(step) &&
        typeof step.label === "string" &&
        typeof step.ok === "boolean"
          ? [
              {
                label: step.label,
                ok: step.ok,
                comment: typeof step.comment === "string" ? step.comment : "",
              },
            ]
          : [],
      )
    : [];
  const verdict: QuizVerdict = {
    result: final ? result : "ungraded",
    // Same mapping as ``Verdict.receipt``: partial is neither right nor wrong.
    is_correct:
      final && result === "correct"
        ? true
        : final && result === "incorrect"
          ? false
          : null,
    final,
    confidence: typeof value.confidence === "number" ? value.confidence : 0,
    steps,
  };
  if (typeof value.feedback === "string" && value.feedback) {
    verdict.feedback = value.feedback;
  }
  if (
    final &&
    typeof value.awarded_points === "number" &&
    typeof value.max_points === "number" &&
    value.max_points > 0 &&
    value.awarded_points >= 0 &&
    value.awarded_points <= value.max_points
  ) {
    verdict.awarded_points = value.awarded_points;
    verdict.max_points = value.max_points;
  }
  if (typeof value.reason === "string" && REASONS.has(value.reason)) {
    verdict.reason = value.reason as QuizVerdictReason;
  }
  return verdict;
}

export interface QuizAssessment {
  is_correct: boolean;
  /** Omitted when the stored result should follow ``is_correct``. */
  result?: AssessmentResult;
}

/**
 * Decide what a submitted answer stores as its assessment.
 *
 * Exact matching stays authoritative for objective questions and for answers
 * it already accepts; the judge can only grade what exact matching cannot.
 * An image answer without a final verdict is ``ungraded`` rather than a
 * mistake.
 */
export function resolveQuizAssessment({
  exactCorrect,
  objective,
  hasImages,
  verdict,
}: {
  exactCorrect: boolean;
  objective: boolean;
  hasImages: boolean;
  verdict: QuizVerdict | null | undefined;
}): QuizAssessment {
  if (objective || exactCorrect) return { is_correct: exactCorrect };
  if (verdict?.final) {
    return { is_correct: verdict.result === "correct", result: verdict.result };
  }
  if (hasImages) return { is_correct: false, result: "ungraded" };
  return { is_correct: false };
}
