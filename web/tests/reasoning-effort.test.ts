import assert from "node:assert/strict";
import test from "node:test";

import {
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
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
});

test("gpt-5.6-sol swaps minimal for none and adds max", () => {
  // Its enum is not the gpt-5 one: `minimal` is a 400 and `max` sits above
  // `xhigh`. The generic gpt-5 branch must not swallow it.
  assert.deepEqual(values("openai", "gpt-5.6-sol"), [
    "",
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
  ]);
  // Sibling gpt-5.6 variants are unconfirmed, so they stay on the gpt-5 list
  // rather than being offered a level they may reject.
  assert.equal(values("openai", "gpt-5.6-luna").includes("max"), false);
});

test("OpenAI-compatible gateways expose explicit effort levels", () => {
  assert.deepEqual(values("custom", "idrouter/qd/lite"), [
    "",
    "none",
    "low",
    "medium",
    "high",
  ]);
  assert.deepEqual(values("openai-compatible", "gateway/model"), [
    "",
    "none",
    "low",
    "medium",
    "high",
  ]);
  assert.deepEqual(values("custom", "gateway/model", "vendor-level"), [
    "",
    "none",
    "low",
    "medium",
    "high",
    "vendor-level",
  ]);
});

test("Anthropic-compatible aliases follow the Anthropic model rules", () => {
  assert.deepEqual(values("anthropic-compatible", "claude-sonnet-4-5"), [
    "",
    "none",
    "low",
    "medium",
    "high",
  ]);
  assert.deepEqual(
    values("anthropic_compatible", "claude-opus-4-6").includes("adaptive"),
    false,
  );
});

test("unknown models stay hidden unless they already carry an override", () => {
  assert.deepEqual(values("openai", "gpt-4o"), []);
  assert.deepEqual(values("unknown", "model", "vendor-level"), [
    "",
    "vendor-level",
  ]);
});

test("managed profiles use only the provider-supported reasoning levels", () => {
  assert.deepEqual(
    reasoningEffortOptionsFromSupportedLevels(["medium", "high"]).map(
      (option) => option.value,
    ),
    ["", "medium", "high"],
  );
  assert.deepEqual(
    reasoningEffortOptionsFromSupportedLevels([
      "high",
      "",
      "high",
      "medium",
    ]).map((option) => option.value),
    ["", "high", "medium"],
  );
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
