import assert from "node:assert/strict";
import test from "node:test";

import {
  dropUnvalidatedReasoningEffort,
  effectiveReasoningEffort,
  normalizeReasoningEffort,
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
  setModelReasoningEffort,
  supportedReasoningEffortValues,
  VALID_REASONING_EFFORTS,
} from "../lib/reasoning-effort";

const values = (binding: string, model: string, current = ""): string[] =>
  reasoningEffortOptions(binding, model, current).map((option) => option.value);

test("MiniMax Flash exposes adaptive effort levels and preserves saved values", () => {
  for (const binding of ["minimax", "minimax_anthropic"]) {
    assert.deepEqual(values(binding, "MiniMax-M3.1-Flash"), [
      "", "low", "medium", "high", "xhigh", "max",
    ]);
    assert.deepEqual(values(binding, "MiniMax-M3"), ["", "none", "adaptive"]);
    assert.equal(values(binding, "MiniMax-M3.1-Flash", "none").includes("none"), true);
  }
});

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
  assert.deepEqual(
    reasoningEffortOptionsFromSupportedLevels(["none", "low", "none"]).map(
      (option) => option.value,
    ),
    ["", "none", "low"],
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


test("GLM effort choices follow the documented model family and retain invalid values for recovery", () => {
  assert.deepEqual(values("openai", "glm-5.3"), ["", "low", "high", "max"]);
  assert.deepEqual(values("zhipu", "glm-5.3"), ["", "low", "high", "max"]);
  assert.deepEqual(values("custom", "z-ai/glm-5.3"), ["", "low", "high", "max"]);
  assert.deepEqual(values("azure", "GLM-5.3"), ["", "low", "high", "max"]);
  assert.deepEqual(values("openai", "glm-4.7"), []);
  assert.deepEqual(values("openai", "glm-5.3-unknown"), []);
  assert.deepEqual(values("openai", "glm-5.3", "medium"), ["", "low", "high", "max", "medium"]);
  assert.deepEqual(values("openai", "glm-4.7", "vendor-level"), ["", "vendor-level"]);
});

test("the wire vocabulary mirrors the backend VALID_REASONING_EFFORTS", () => {
  // deeptutor/services/model_selection/llm.py::VALID_REASONING_EFFORTS. A
  // turn's llm_selection.reasoning_effort is rejected outside this set, so
  // chat-side pickers filter on it.
  assert.deepEqual([...VALID_REASONING_EFFORTS].sort(), [
    "high",
    "low",
    "max",
    "medium",
    "minimal",
    "none",
    "xhigh",
  ]);
});

test("normalizeReasoningEffort keeps legal values and drops everything else", () => {
  assert.equal(normalizeReasoningEffort("  High "), "high");
  assert.equal(normalizeReasoningEffort("xhigh"), "xhigh");
  assert.equal(normalizeReasoningEffort(""), null);
  assert.equal(normalizeReasoningEffort("   "), null);
  assert.equal(normalizeReasoningEffort(null), null);
  assert.equal(normalizeReasoningEffort(42), null);
  // Provider-specific levels live outside the turn vocabulary.
  assert.equal(normalizeReasoningEffort("adaptive"), null);
});

test("effectiveReasoningEffort drops overrides the selected model rejects (#641)", () => {
  const restricted = {
    provider: "openai",
    model: "gpt-5.2",
    supported_reasoning_efforts: ["low", "high"],
  };
  assert.equal(effectiveReasoningEffort(restricted, "xhigh"), null);
  assert.equal(effectiveReasoningEffort(restricted, "high"), "high");
  assert.equal(effectiveReasoningEffort(restricted, null), null);
  // An unresolved option cannot validate anything: the override is not
  // effective, so send paths fall back to the configured default.
  assert.equal(effectiveReasoningEffort(null, "high"), null);
});

test("supportedReasoningEffortValues never adds a stale stored value (#641)", () => {
  // Catalog list wins when published, narrowed to the wire vocabulary.
  assert.deepEqual(
    supportedReasoningEffortValues({
      provider: "openai",
      model: "gpt-5.2",
      supported_reasoning_efforts: ["low", "high", "adaptive"],
    }),
    ["low", "high"],
  );
  // Fallback table path: the tables' own reset-recovery retention is
  // bypassed, so a value they would re-add for a stored override is absent.
  const gemini = supportedReasoningEffortValues({
    provider: "gemini",
    model: "gemini-3.6-flash",
  });
  assert.deepEqual(gemini, ["minimal", "low", "medium", "high"]);
  assert.equal(gemini.includes("none"), false);
  assert.equal(gemini.includes("xhigh"), false);
  // declared_reasoning is honoured on the table path too.
  assert.deepEqual(
    supportedReasoningEffortValues({
      provider: "unknown",
      model: "mystery",
      declared_reasoning: true,
    }),
    ["none", "low", "medium", "high"],
  );
  assert.deepEqual(
    supportedReasoningEffortValues({
      provider: "openai",
      model: "gpt-5.2",
      declared_reasoning: false,
    }),
    [],
  );
  assert.deepEqual(supportedReasoningEffortValues(null), []);
});

test("a restored xhigh override never reaches the wire once the model restricts levels (#641)", () => {
  // Restore step: `xhigh` is legal wire vocabulary, so asLLMSelection-style
  // normalization keeps it in the conversation's selection.
  const restored = {
    profile_id: "p-alt",
    model_id: "m-alt",
    reasoning_effort: normalizeReasoningEffort("xhigh"),
  };
  assert.equal(restored.reasoning_effort, "xhigh");
  // Submit step: the option resolved from the catalog restricts the model.
  const option = {
    provider: "openai",
    model: "gpt-5.2",
    supported_reasoning_efforts: ["low", "high"],
  };
  const outgoing = dropUnvalidatedReasoningEffort(restored, option);
  assert.notEqual(outgoing, null);
  assert.equal("reasoning_effort" in (outgoing as object), false);
  // Options still loading / profile gone: the override is omitted rather
  // than forwarded unvalidated (falls back to the configured default).
  const unresolved = dropUnvalidatedReasoningEffort(restored, null);
  assert.equal("reasoning_effort" in (unresolved as object), false);
  // A still-supported override passes through untouched.
  const kept = dropUnvalidatedReasoningEffort(
    { ...restored, reasoning_effort: "high" },
    option,
  );
  assert.equal(kept?.reasoning_effort, "high");
  // Selections without an override are returned as-is.
  const plain: {
    profile_id: string;
    model_id: string;
    reasoning_effort?: string | null;
  } = { profile_id: "p-alt", model_id: "m-alt" };
  assert.equal(dropUnvalidatedReasoningEffort(plain, null), plain);
  assert.equal(dropUnvalidatedReasoningEffort(null, option), null);
});
