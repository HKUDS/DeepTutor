import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildReaderLearningPrompt,
  READER_LEARNING_ACTION_EVENT,
} from "../lib/reading-learning-actions";

test("learning prompts stay grounded in the current unit and age band", () => {
  const prompt = buildReaderLearningPrompt(
    "learn",
    { locator: 12, unit: "页", ageBand: "9-12" },
  );

  assert.match(prompt, /第 12 页/);
  assert.match(prompt, /9-12 岁/);
  assert.match(prompt, /只依据当前阅读材料/);
  assert.match(prompt, /最多三/);
  assert.equal(READER_LEARNING_ACTION_EVENT, "dt:reader-learning-action");
});

test("quiz prompt asks one question at a time and stores no score", () => {
  const prompt = buildReaderLearningPrompt(
    "quiz",
    { locator: 3, unit: "chapter", ageBand: "9-12" },
    "en",
  );

  assert.match(prompt, /chapter 3/);
  assert.match(prompt, /Ask only question 1 first/);
  assert.match(prompt, /Do not list all questions at once/);
  assert.match(prompt, /or save a score/);
});
