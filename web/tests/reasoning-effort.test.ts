import assert from "node:assert/strict";
import test from "node:test";

import {
  reasoningEffortOptions,
  setModelReasoningEffort,
} from "../lib/reasoning-effort";

const values = (
  binding: string,
  model: string,
  current = "",
): string[] =>
  reasoningEffortOptions(binding, model, current).map((option) => option.value);

test("Gemini 3 and 2.5 Pro never offer the invalid none effort", () => {
  assert.deepEqual(values("gemini", "gemini-3.6-flash"), [
    "",
    "minimal",
    "low",
    "medium",
    "high",
  ]);
  assert.equal(values("gemini", "gemini-2.5-pro").includes("none"), false);
});

test("Gemini 2.5 Flash can explicitly disable reasoning", () => {
  assert.deepEqual(values("gemini", "gemini-2.5-flash"), [
    "",
    "none",
    "low",
    "medium",
    "high",
  ]);
});

test("known reasoning families get conservative provider-specific choices", () => {
  assert.deepEqual(values("openai", "gpt-5.2"), [
    "",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
  ]);
  assert.deepEqual(values("anthropic", "claude-sonnet-4-5"), [
    "",
    "none",
    "low",
    "medium",
    "high",
    "adaptive",
  ]);
  assert.deepEqual(values("dashscope", "qwen3-max"), [
    "",
    "minimal",
    "high",
  ]);
  assert.deepEqual(values("custom", "deepseek-reasoner"), [
    "",
    "minimal",
    "high",
  ]);
});

test("unknown models stay hidden unless they already carry an override", () => {
  assert.deepEqual(values("openai", "gpt-4o"), []);
  assert.deepEqual(values("unknown", "model", "vendor-level"), [
    "",
    "vendor-level",
  ]);
});

test("Auto removes the catalog field instead of persisting an empty string", () => {
  const model: { reasoning_effort?: string } = {
    reasoning_effort: "high",
  };
  setModelReasoningEffort(model, "");
  assert.equal("reasoning_effort" in model, false);

  setModelReasoningEffort(model, " medium ");
  assert.equal(model.reasoning_effort, "medium");
});
