import test from "node:test";
import assert from "node:assert/strict";

import {
  isChoiceQuizQuestion,
  isConceptQuizQuestion,
  isFillInBlankQuizQuestion,
  normalizeQuizQuestionType,
  resolveChoiceAnswerKey,
  resolveConceptAnswer,
} from "../lib/quiz-question-type";
import { extractQuizQuestions } from "../lib/quiz-types";

test("normalizeQuizQuestionType maps legacy choice aliases to choice", () => {
  assert.equal(normalizeQuizQuestionType("choice"), "choice");
  assert.equal(normalizeQuizQuestionType("multiple_choice"), "choice");
  assert.equal(normalizeQuizQuestionType("multiple choice"), "choice");
  assert.equal(normalizeQuizQuestionType("mcq"), "choice");
  assert.equal(isChoiceQuizQuestion("multiple_choice"), true);
});

test("normalizeQuizQuestionType preserves every canonical type", () => {
  assert.equal(normalizeQuizQuestionType("written"), "written");
  assert.equal(normalizeQuizQuestionType("essay"), "written");
  assert.equal(normalizeQuizQuestionType("short_answer"), "short_answer");
  assert.equal(normalizeQuizQuestionType("concept"), "concept");
  assert.equal(normalizeQuizQuestionType("true_false"), "concept");
  assert.equal(normalizeQuizQuestionType("fill_in_blank"), "fill_in_blank");
  assert.equal(normalizeQuizQuestionType("fill-in-the-blank"), "fill_in_blank");
  assert.equal(normalizeQuizQuestionType("coding"), "coding");
  assert.equal(normalizeQuizQuestionType("programming"), "coding");
  assert.equal(isConceptQuizQuestion("true_false"), true);
  assert.equal(isFillInBlankQuizQuestion("fill-in-the-blank"), true);
});

test("resolveConceptAnswer normalizes T/F variants", () => {
  assert.equal(resolveConceptAnswer("true"), "true");
  assert.equal(resolveConceptAnswer("TRUE"), "true");
  assert.equal(resolveConceptAnswer("false"), "false");
  assert.equal(resolveConceptAnswer(""), "");
  assert.equal(resolveConceptAnswer("maybe"), "");
});

test("resolveChoiceAnswerKey accepts either the option key or label text", () => {
  const options = {
    A: "Alpha",
    B: "Beta",
    C: "Gamma",
    D: "Delta",
  };

  assert.equal(resolveChoiceAnswerKey("C", options), "C");
  assert.equal(resolveChoiceAnswerKey("gamma", options), "C");
});

test("extractQuizQuestions normalizes legacy question types from payloads", () => {
  const questions = extractQuizQuestions({
    summary: {
      results: [
        {
          qa_pair: {
            question_id: "q_1",
            question: "Pick the best answer.",
            question_type: "multiple_choice",
            options: { A: "One", B: "Two", C: "Three", D: "Four" },
            correct_answer: "B",
            explanation: "Because two is correct.",
          },
        },
      ],
    },
  });

  assert.ok(questions);
  assert.equal(questions?.[0]?.question_type, "choice");
});
