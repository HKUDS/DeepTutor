import test from "node:test";
import assert from "node:assert/strict";

import {
  createInitialWordHintState,
  reduceWordHintState,
  type KidsWordHintState,
} from "../lib/kids-learning/word-hint";

test("guided word hint reveals help in three stages", () => {
  let state = createInitialWordHintState("plum");
  assert.equal(state.phase, "hint");
  assert.equal(state.chinese, undefined);

  state = reduceWordHintState(state, {
    type: "show-choices",
    choices: ["small sweet fruit", "a big animal", "a noisy machine"],
  });
  assert.equal(state.phase, "choices");
  assert.equal(state.choices.length, 3);
  assert.equal(state.chinese, undefined);

  state = reduceWordHintState(state, {
    type: "check",
    correct: false,
    attempt: 1,
    feedback: "Think again",
  });
  assert.equal(state.phase, "choices");
  assert.equal(state.chinese, undefined);

  state = reduceWordHintState(state, {
    type: "check",
    correct: false,
    attempt: 2,
    feedback: "Let us look together",
    correctChoice: "small sweet fruit",
    chinese: "李子",
    explanation: "A plum is a small sweet fruit.",
  });
  assert.equal(state.phase, "reveal");
  assert.equal(state.correctChoice, "small sweet fruit");
  assert.equal(state.chinese, "李子");
});

test("answering correctly does not leak Chinese", () => {
  let state: KidsWordHintState = createInitialWordHintState("mat");
  state = reduceWordHintState(state, {
    type: "show-choices",
    choices: ["something on the floor", "a kind of truck", "a winter hat"],
  });
  state = reduceWordHintState(state, {
    type: "check",
    correct: true,
    attempt: 1,
    feedback: "Yes",
  });

  assert.equal(state.phase, "correct");
  assert.equal(state.chinese, undefined);
});
