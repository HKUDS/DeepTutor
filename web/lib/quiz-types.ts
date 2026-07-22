/**
 * Shared types for Quiz Generation (deep_question capability).
 */

import {
  type NormalizedQuizQuestionType,
  normalizeQuizQuestionType,
} from "./quiz-question-type";

export type DeepQuestionMode = "custom" | "mimic";

export interface DeepQuestionFormConfig {
  mode: DeepQuestionMode;
  topic: string;
  num_questions: number;
  difficulty: string;
  /**
   * Multi-select allowed-types whitelist. Empty list = "auto" (planner
   * picks any type per question). When ≥1 type is selected, the planner
   * is restricted to those types.
   */
  question_types: NormalizedQuizQuestionType[];
  /**
   * Per-type quantity targets (sums to num_questions when non-empty).
   * Only populated when ≥2 types are selected and the user has tweaked
   * the ratio bar; empty means "distribute evenly across allowed types".
   */
  per_type_counts: Partial<Record<NormalizedQuizQuestionType, number>>;
  paper_path: string;
  max_questions: number;
}

export const DEFAULT_QUIZ_CONFIG: DeepQuestionFormConfig = {
  mode: "custom",
  topic: "",
  num_questions: 3,
  difficulty: "auto",
  question_types: [],
  per_type_counts: {},
  paper_path: "",
  max_questions: 10,
};

export interface QuizQuestion {
  question_id: string;
  question: string;
  question_type: NormalizedQuizQuestionType;
  options?: Record<string, string>;
  correct_answer: string;
  explanation: string;
  difficulty?: string;
  concentration?: string;
  knowledge_context?: string;
}

export interface QuizFollowupContext {
  parent_quiz_session_id?: string;
  question_id: string;
  question: string;
  question_type: QuizQuestion["question_type"];
  options?: Record<string, string>;
  correct_answer: string;
  explanation: string;
  difficulty?: string;
  concentration?: string;
  knowledge_context?: string;
  user_answer?: string;
  is_correct?: boolean;
  /**
   * Filenames of the images the learner attached as their answer. Image
   * bytes ride on the first follow-up message as regular attachments so
   * vision-capable models see them; the filenames here let the follow-up
   * system prompt mention them explicitly so the LLM knows the attached
   * images are the learner's answer, not unrelated context.
   */
  user_answer_image_filenames?: string[];
  /** Latest AI judgment text for this question, when one has been run. */
  ai_judgment?: string;
}

/**
 * Extract QuizQuestion[] from per-question ``content`` events emitted live
 * by the new ``QuestionPipeline`` while the quizzing phase is running.
 *
 * The backend tags each event with ``metadata.call_kind ===
 * "quiz_question_emitted"`` and the structured ``qa_pair`` payload. We
 * collect them, dedupe by ``question_id``, and order by
 * ``question_index`` so QuizViewer can render each question the moment
 * it lands — without waiting for the final ``result`` event.
 *
 * Returns ``null`` until at least one valid quiz event has arrived, so
 * the caller can fall back to the legacy ``extractQuizQuestions`` shape
 * for older (mimic) result envelopes.
 */
export function extractStreamingQuizQuestions(
  events: Array<{
    type?: string;
    metadata?: Record<string, unknown> | undefined;
  }>,
): QuizQuestion[] | null {
  if (!Array.isArray(events) || events.length === 0) return null;
  const byId = new Map<string, { idx: number; qa: QuizQuestion }>();
  for (const event of events) {
    if (event.type !== "content") continue;
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (meta.call_kind !== "quiz_question_emitted") continue;
    const qa = meta.qa_pair as Record<string, unknown> | undefined;
    if (!qa || typeof qa !== "object" || !qa.question) continue;
    const idx = Number(meta.question_index);
    const question: QuizQuestion = {
      question_id: String(qa.question_id ?? ""),
      question: String(qa.question ?? ""),
      question_type: normalizeQuizQuestionType(qa.question_type),
      options: qa.options as Record<string, string> | undefined,
      correct_answer: String(qa.correct_answer ?? ""),
      explanation: String(qa.explanation ?? ""),
      difficulty: qa.difficulty ? String(qa.difficulty) : undefined,
      concentration: qa.concentration ? String(qa.concentration) : undefined,
    };
    const key = question.question_id || String(idx);
    byId.set(key, {
      idx: Number.isFinite(idx) ? idx : byId.size,
      qa: question,
    });
  }
  if (byId.size === 0) return null;
  return Array.from(byId.values())
    .sort((a, b) => a.idx - b.idx)
    .map((entry) => entry.qa);
}

/**
 * Extract QuizQuestion[] from the raw `result` event metadata returned by
 * the deep_question capability.
 */
export function extractQuizQuestions(
  resultMetadata: Record<string, unknown> | undefined,
): QuizQuestion[] | null {
  if (!resultMetadata) return null;
  const summary = resultMetadata.summary as Record<string, unknown> | undefined;
  if (!summary) return null;
  const results = summary.results as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(results) || results.length === 0) return null;

  const parsed: Array<QuizQuestion | null> = results.map((item) => {
    const qa = (item.qa_pair ?? item) as Record<string, unknown>;
    if (!qa.question) return null;
    const question: QuizQuestion = {
      question_id: String(qa.question_id ?? ""),
      question: String(qa.question ?? ""),
      question_type: normalizeQuizQuestionType(qa.question_type),
      options: qa.options as Record<string, string> | undefined,
      correct_answer: String(qa.correct_answer ?? ""),
      explanation: String(qa.explanation ?? ""),
      difficulty: qa.difficulty ? String(qa.difficulty) : undefined,
      concentration: qa.concentration ? String(qa.concentration) : undefined,
      knowledge_context:
        qa.metadata &&
        typeof qa.metadata === "object" &&
        "knowledge_context" in qa.metadata &&
        qa.metadata.knowledge_context
          ? String(qa.metadata.knowledge_context)
          : undefined,
    };
    return question;
  });

  return parsed.filter(
    (question): question is QuizQuestion => question !== null,
  );
}

export interface QuizFollowupExtras {
  /** Filenames of the learner's image answers (bytes ride on first msg). */
  userAnswerImageFilenames?: string[] | null;
  /** Last AI-judgment text for this question, if the learner ran it. */
  aiJudgment?: string | null;
}

export function buildQuizFollowupConfig(
  question: QuizQuestion,
  userAnswer: string,
  isCorrect: boolean | null,
  parentQuizSessionId?: string | null,
  extras?: QuizFollowupExtras,
): Record<string, unknown> {
  const filenames = (extras?.userAnswerImageFilenames ?? [])
    .map((name) => (typeof name === "string" ? name.trim() : ""))
    .filter((name) => name.length > 0);
  const context: QuizFollowupContext = {
    question_id: question.question_id,
    question: question.question,
    question_type: question.question_type,
    options: question.options,
    correct_answer: question.correct_answer,
    explanation: question.explanation,
    difficulty: question.difficulty,
    concentration: question.concentration,
    knowledge_context: question.knowledge_context,
    user_answer: userAnswer || undefined,
    is_correct: typeof isCorrect === "boolean" ? isCorrect : undefined,
    parent_quiz_session_id: parentQuizSessionId || undefined,
    user_answer_image_filenames: filenames.length > 0 ? filenames : undefined,
    ai_judgment: extras?.aiJudgment?.trim() || undefined,
  };

  return {
    followup_question_context: context,
  };
}

function titleCase(value: string): string {
  if (!value) return "";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export const QUIZ_TYPE_LABEL_KEYS: Record<NormalizedQuizQuestionType, string> =
  {
    choice: "Multiple Choice",
    concept: "Concept Question",
    fill_in_blank: "Fill in the Blank",
    short_answer: "Short Answer",
    written: "Essay",
    coding: "Coding",
  };

/**
 * One-line summary of the quiz form, shown next to the collapsed `Settings`
 * chevron in the composer. Pass `translate` (`t` from `react-i18next`) so the
 * summary follows the active UI language.
 */
export function summarizeQuizConfig(
  cfg: DeepQuestionFormConfig,
  translate?: (key: string) => string,
): string {
  const tr = translate ?? ((s: string) => s);
  if (cfg.mode === "mimic") {
    const target = cfg.paper_path.trim() || tr("no paper");
    return [
      tr("Mimic Paper"),
      target,
      `${tr("Max")} ${cfg.max_questions}`,
    ].join(" · ");
  }
  const typeSummary =
    cfg.question_types.length === 0
      ? tr("Auto")
      : cfg.question_types.length === 1
        ? tr(QUIZ_TYPE_LABEL_KEYS[cfg.question_types[0]])
        : `${cfg.question_types.length} ${tr("types")}`;
  return [
    tr("Custom"),
    `${cfg.num_questions} ${tr("questions")}`,
    tr(titleCase(cfg.difficulty || "auto")),
    typeSummary,
  ].join(" · ");
}

/**
 * Build the `config` payload to send over WebSocket for a quiz generation
 * request.
 */
export function buildQuizWSConfig(
  cfg: DeepQuestionFormConfig,
): Record<string, unknown> {
  if (cfg.mode === "mimic") {
    return {
      mode: "mimic",
      paper_path: cfg.paper_path.trim(),
      max_questions: cfg.max_questions,
    };
  }
  // Only forward per-type counts when >=2 types are selected AND the user
  // actually populated counts that sum to num_questions. Otherwise let
  // the backend distribute freely across the allowed set.
  const countsValid =
    cfg.question_types.length >= 2 &&
    Object.keys(cfg.per_type_counts).length > 0 &&
    Object.values(cfg.per_type_counts).reduce((sum, v) => sum + (v || 0), 0) ===
      cfg.num_questions;
  return {
    mode: "custom",
    num_questions: cfg.num_questions,
    difficulty: cfg.difficulty === "auto" ? "" : cfg.difficulty,
    question_types: cfg.question_types,
    per_type_counts: countsValid ? cfg.per_type_counts : {},
  };
}
