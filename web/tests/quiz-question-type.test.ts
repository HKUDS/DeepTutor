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

test("extractQuizQuestions decodes dense unicode escapes in card text", () => {
  const questions = extractQuizQuestions({
    summary: {
      results: [
        {
          qa_pair: {
            question_id: "q_1",
            question:
              "\\u300c\\u6570\\u5236\\u8f6c\\u6362\\u300d\\u8fd8\\u6ca1\\u8fc7\\u5173\\uff1f",
            question_type: "choice",
            options: {
              A: "\\u662f\\u7684\\uff0c\\u5df2\\u7ecf\\u8fc7\\u5173",
              B: "\\u8fd8\\u6ca1\\u6709",
            },
            correct_answer: "B",
            explanation:
              "\\u9898\\u5e72\\u91cc\\u7684\\u8f6c\\u4e49\\u5e94\\u88ab\\u89e3\\u7801",
          },
        },
      ],
    },
  });

  assert.ok(questions);
  assert.equal(questions?.[0]?.question, "「数制转换」还没过关？");
  assert.equal(questions?.[0]?.options?.A, "是的，已经过关");
  assert.equal(questions?.[0]?.options?.B, "还没有");
  assert.equal(questions?.[0]?.explanation, "题干里的转义应被解码");
});
