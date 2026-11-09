import { expect, it } from "vitest";

import type { LLMOption } from "@/lib/llm-options";
import {
  asLLMSelection,
  sanitizeOutgoingLLMSelection,
} from "@/features/chat/ChatStateAdapter";

const option = (overrides: Partial<LLMOption>): LLMOption =>
  ({
    profile_id: "p-alt",
    model_id: "m-alt",
    profile_name: "Alt",
    model_name: "Alt Model",
    model: "gpt-5.2",
    provider: "openai",
    is_active_default: false,
    ...overrides,
  }) as LLMOption;

it("restores a globally legal xhigh override but never submits it once the model restricts to low/high (#641)", () => {
  // Restore step: `xhigh` is legal wire vocabulary, so asLLMSelection keeps
  // it in the conversation's persisted selection.
  const restored = asLLMSelection({
    profile_id: "p-alt",
    model_id: "m-alt",
    reasoning_effort: "xhigh",
  });
  expect(restored?.reasoning_effort).toBe("xhigh");
  // Submit step: the catalog restricts the model to low/high, so the
  // outgoing llm_selection must not forward the stale override.
  const submitted = sanitizeOutgoingLLMSelection(restored, [
    option({ supported_reasoning_efforts: ["low", "high"] }),
  ]);
  expect(submitted).toEqual({ profile_id: "p-alt", model_id: "m-alt" });
});

it("forwards a still-supported override untouched (#641)", () => {
  const restored = asLLMSelection({
    profile_id: "p-alt",
    model_id: "m-alt",
    reasoning_effort: "high",
  });
  expect(
    sanitizeOutgoingLLMSelection(restored, [
      option({ supported_reasoning_efforts: ["low", "high"] }),
    ]),
  ).toEqual(restored);
});

it("omits an override that cannot be validated against the catalog (#641)", () => {
  // Options still loading or the profile no longer listed: the override is
  // dropped rather than forwarded unvalidated, so the turn falls back to the
  // configured default.
  const restored = asLLMSelection({
    profile_id: "p-alt",
    model_id: "m-alt",
    reasoning_effort: "high",
  });
  expect(sanitizeOutgoingLLMSelection(restored, [])).toEqual({
    profile_id: "p-alt",
    model_id: "m-alt",
  });
});
