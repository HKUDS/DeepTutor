import assert from "node:assert/strict";
import test from "node:test";

import {
  llmSelectionKey,
  normalizeLLMSelection,
  sameLLMSelection,
  withLLMReasoningEffort,
} from "../lib/llm-options";

test("normalizing preserves the conversation reasoning override", () => {
  assert.deepEqual(
    normalizeLLMSelection({
      profile_id: " p1 ",
      model_id: " m1 ",
      reasoning_effort: " HIGH ",
    }),
    { profile_id: "p1", model_id: "m1", reasoning_effort: "high" },
  );
  assert.equal(normalizeLLMSelection({ profile_id: "p1" }), null);
});

test("normalizing drops values the backend would reject", () => {
  assert.deepEqual(
    normalizeLLMSelection({
      profile_id: "p1",
      model_id: "m1",
      reasoning_effort: "adaptive",
    }),
    { profile_id: "p1", model_id: "m1" },
  );
});

test("model identity ignores effort while the override remains editable", () => {
  const base = { profile_id: "p1", model_id: "m1" };
  const high = withLLMReasoningEffort(base, "high");
  const auto = withLLMReasoningEffort(high, " ");

  assert.deepEqual(high, { ...base, reasoning_effort: "high" });
  assert.deepEqual(auto, base);
  assert.equal(llmSelectionKey(high), llmSelectionKey(base));
  assert.equal(sameLLMSelection(high, auto), true);
  assert.equal("reasoning_effort" in auto, false);
});
