import assert from "node:assert/strict";
import test from "node:test";

import {
  reasoningEffortOptions,
  setModelReasoningEffort,
} from "../lib/reasoning-effort";

const values = (binding: string, model: string, current = ""): string[] =>
  reasoningEffortOptions(binding, model, current).map((option) => option.value);

test("Gemini 3 and 2.5 Pro do not list the invalid none effort", () => {
  assert.deepEqual(values("gemini", "gemini-3.6-flash"), [
    "",
    "minimal",
    "low",
    "medium",
    "high",
  ]);
  assert.equal(values("gemini", "gemini-2.5-pro").includes("none"), false);
});

test("a stored value this table excludes stays visible so it can be reset", () => {
  // The recovery path for a profile already sending a rejected value: it has
  // to be selectable to be switched back to Auto.
  assert.deepEqual(values("gemini", "gemini-3.6-flash", "none"), [
    "",
    "minimal",
    "low",
    "medium",
    "high",
    "none",
  ]);
});

test("provider aliases resolve to the canonical adapter", () => {
  assert.deepEqual(values("google", "gemini-2.5-flash"), [
    "",
    "none",
    "low",
    "medium",
    "high",
  ]);
  assert.deepEqual(values("azure", "gpt-5.2"), [
    "",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
  ]);
  assert.deepEqual(values("claude", "claude-opus-5"), ["", "none", "adaptive"]);
});

test("effort-based Claude families offer adaptive, older ones do not", () => {
  // Opus 4.7+ reject enabled+budget_tokens and every real level collapses to
  // adaptive; the older families 400 on adaptive instead.
  for (const model of ["claude-opus-4-7", "claude-opus-5", "claude-fable-5"]) {
    assert.deepEqual(values("anthropic", model), ["", "none", "adaptive"]);
  }
  assert.equal(
    values("anthropic", "claude-opus-4-6").includes("adaptive"),
    false,
  );
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
  ]);
  assert.deepEqual(values("dashscope", "qwen3-max"), ["", "minimal", "high"]);
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
