/**
 * Reading a mastery question — and its verdict — out of a turn's events.
 *
 * A mastery question is graded work, not a clarifying question: it names the
 * objective it is testing, it is the Nth attempt at that objective, it has a
 * difficulty, and it ends in a ruling with an explanation. So it travels on
 * its own tool-metadata key, `mastery_question`, and this module is the only
 * place that knows its shape — the generic `ask_user` card and everything
 * written against it are a different thing entirely.
 *
 * It used to ride the `ask_user` channel, marked with a `kind` every reader
 * had to branch on. Questions posed before that changed are still in the
 * history, so `readPosedQuestion` also reads the old envelope.
 *
 * The verdict arrives separately, on the `mastery_grade` tool result — often a
 * round later than the question. Indexing it by question id here is what lets
 * the card that asked show the answer, rather than leaving the learner to find
 * it in the prose below.
 */

import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultPayload } from "@/lib/tool-event";

/** Tool-metadata key the posed card travels under. */
export const MASTERY_QUESTION_KEY = "mastery_question";
/**
 * The `kind` marker on the older `ask_user`-shaped card. Only history carries
 * it; nothing posed now needs a discriminator, because the key *is* the
 * discriminator.
 */
export const MASTERY_QUESTION_KIND = MASTERY_QUESTION_KEY;

export interface MasteryQuestionOption {
  label: string;
  body: string;
}

export interface MasteryQuestion {
  questionId: string;
  prompt: string;
  questionType: string;
  objectiveName: string;
  difficulty: string;
  attempt: number;
  options: MasteryQuestionOption[];
  allowFreeText: boolean;
}

export interface MasteryGradeResult {
  questionId: string;
  isCorrect: boolean;
  learnerAnswer: string;
  correctLabel: string;
  correctBody: string;
  explanation: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function parseQuestion(value: unknown): MasteryQuestion | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const questionId = text(raw.question_id).trim();
  if (!questionId) return null;
  const objective = asRecord(raw.objective);
  const options = Array.isArray(raw.options)
    ? raw.options
        .map((entry) => asRecord(entry))
        .filter((entry): entry is Record<string, unknown> => entry !== null)
        .map((entry) => ({
          label: text(entry.label),
          body: text(entry.body),
        }))
        .filter((option) => option.label)
    : [];
  const attempt = Number(raw.attempt);
  return {
    questionId,
    prompt: text(raw.prompt),
    questionType: text(raw.question_type) || "short",
    objectiveName: text(objective?.name).trim(),
    difficulty: text(raw.difficulty).trim(),
    attempt: Number.isFinite(attempt) && attempt > 0 ? Math.floor(attempt) : 1,
    options,
    allowFreeText: raw.allow_free_text !== false,
  };
}

function parseGrade(value: unknown): MasteryGradeResult | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const questionId = text(raw.question_id).trim();
  if (!questionId) return null;
  return {
    questionId,
    isCorrect: raw.is_correct === true,
    learnerAnswer: text(raw.learner_answer),
    correctLabel: text(raw.correct_label),
    correctBody: text(raw.correct_body),
    explanation: text(raw.explanation),
  };
}

/**
 * The mastery question a single event posed, or null if it posed none.
 *
 * The one place that knows where a posed card lives on the wire, so the
 * surfaces that lay out a message (interleaving cards with text) and the ones
 * that only count them read the same thing. The older `ask_user`-shaped
 * envelope is read too, for cards already in a learner's history.
 */
export function readPosedQuestion(event: StreamEvent): MasteryQuestion | null {
  if (event.type !== "tool_result") return null;
  const own = parseQuestion(
    toolResultPayload(event.metadata, MASTERY_QUESTION_KEY),
  );
  if (own) return own;
  const askUser = asRecord(toolResultPayload(event.metadata, "ask_user"));
  if (!askUser || askUser.kind !== MASTERY_QUESTION_KIND) return null;
  return parseQuestion(askUser[MASTERY_QUESTION_KIND]);
}

/**
 * Every mastery question this message posed, by question id.
 *
 * Keyed rather than reduced to one because a single turn poses several: the
 * turn resumes on the same message after each answer, so a learner working an
 * objective ends up with a run of cards in one message. Each of those cards
 * has to render its own question, and the id is what tells them apart.
 */
export function collectMasteryQuestions(
  events: StreamEvent[] | undefined,
): Map<string, MasteryQuestion> {
  const questions = new Map<string, MasteryQuestion>();
  for (const event of events ?? []) {
    const question = readPosedQuestion(event);
    if (question) questions.set(question.questionId, question);
  }
  return questions;
}

/**
 * The mastery question this message posed last, or null when it posed none.
 *
 * For the surfaces that render one card per message; where the cards are
 * inlined in stream order, use :func:`collectMasteryQuestions` so each card
 * gets its own question rather than all of them showing the last one.
 */
export function extractMasteryQuestion(
  events: StreamEvent[] | undefined,
): MasteryQuestion | null {
  const questions = [...collectMasteryQuestions(events).values()];
  return questions.length ? questions[questions.length - 1] : null;
}

/**
 * Every graded verdict in this conversation, by question id.
 *
 * Built across all messages rather than per message: the ruling usually lands
 * in the same turn as the question, but a learner who answers in the composer
 * instead of on the card is graded a turn later, and the card should show the
 * answer either way.
 */
export function collectMasteryGrades(
  messages: Array<{ events?: StreamEvent[] }>,
): Map<string, MasteryGradeResult> {
  const grades = new Map<string, MasteryGradeResult>();
  for (const message of messages) {
    for (const event of message.events ?? []) {
      if (event.type !== "tool_result") continue;
      const payload = asRecord(
        toolResultPayload(event.metadata, "mastery_grade"),
      );
      const grade = parseGrade(payload?.result);
      if (grade) grades.set(grade.questionId, grade);
    }
  }
  return grades;
}

/**
 * Every question the learner declined, by question id.
 *
 * A skip is a verdict of its own: the engine drops the question without an
 * attempt, so no grade will ever arrive for it, and a card left looking
 * answerable would send an answer nothing is waiting for. Collected across
 * messages for the same reason grades are — the skip rides on the turn that
 * follows the one that posed the card.
 */
export function collectMasterySkips(
  messages: Array<{ events?: StreamEvent[] }>,
): Set<string> {
  const skipped = new Set<string>();
  for (const message of messages) {
    for (const event of message.events ?? []) {
      if (event.type !== "tool_result") continue;
      const payload = asRecord(
        toolResultPayload(event.metadata, "mastery_skip_question"),
      );
      if (!payload || payload.skipped !== true) continue;
      const questionId = text(payload.question_id).trim();
      if (questionId) skipped.add(questionId);
    }
  }
  return skipped;
}
