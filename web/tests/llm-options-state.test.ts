import test from "node:test";
import assert from "node:assert/strict";

import {
  INITIAL_LLM_OPTIONS_STATE,
  reduceLLMOptionsState,
  type LLMOptionsState,
} from "../lib/llm-options-state";
import type { LLMOptionsResponse } from "../lib/llm-options";

const CATALOG: LLMOptionsResponse = {
  active: { profile_id: "profile-1", model_id: "model-1" },
  options: [
    {
      profile_id: "profile-1",
      model_id: "model-1",
      profile_name: "Primary",
      model_name: "Tutor",
      model: "tutor-v1",
      provider: "openai",
      is_active_default: true,
    },
  ],
};

function readyState(): LLMOptionsState {
  return reduceLLMOptionsState(INITIAL_LLM_OPTIONS_STATE, {
    type: "refresh-succeeded",
    payload: CATALOG,
  });
}

test("background model refresh keeps the current catalog visible", () => {
  const ready = readyState();
  const refreshing = reduceLLMOptionsState(ready, {
    type: "refresh-started",
    background: true,
  });

  assert.strictEqual(refreshing, ready);
  assert.equal(refreshing.status, "ready");
  assert.deepEqual(refreshing.options, CATALOG.options);
});

test("failed background model refresh preserves the last usable catalog", () => {
  const failed = reduceLLMOptionsState(readyState(), {
    type: "refresh-failed",
  });

  assert.equal(failed.status, "ready");
  assert.deepEqual(failed.options, CATALOG.options);
  assert.deepEqual(failed.activeDefault, CATALOG.active);
});

test("initial model refresh failure surfaces an error", () => {
  const failed = reduceLLMOptionsState(INITIAL_LLM_OPTIONS_STATE, {
    type: "refresh-failed",
  });

  assert.equal(failed.status, "error");
  assert.deepEqual(failed.options, []);
});
