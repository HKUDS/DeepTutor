import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import ModelSelector from "../components/chat/home/ModelSelector";
import type { LLMOption } from "../lib/llm-options";

const reasoningModel: LLMOption = {
  profile_id: "codex",
  model_id: "sol",
  profile_name: "Codex",
  model_name: "GPT 5.6 Sol",
  model: "gpt-5.6-sol",
  provider: "openai_codex",
  provider_label: "OpenAI Codex",
  supported_reasoning_levels: ["minimal", "medium", "xhigh", "max"],
  is_active_default: true,
};

function renderModelSelector(value: LLMOption["reasoning_effort"]) {
  return renderToStaticMarkup(
    React.createElement(ModelSelector, {
      options: [reasoningModel],
      activeDefault: {
        profile_id: reasoningModel.profile_id,
        model_id: reasoningModel.model_id,
      },
      value: {
        profile_id: reasoningModel.profile_id,
        model_id: reasoningModel.model_id,
        reasoning_effort: value,
      },
      loading: false,
      error: false,
      placement: "top",
      onChange: () => {},
    }),
  );
}

test("the composer model control exposes conversation reasoning effort", () => {
  const source = readFileSync(
    path.resolve(process.cwd(), "components/chat/home/ModelSelector.tsx"),
    "utf8",
  );

  assert.match(source, /conversationReasoningEffortOptions\(/);
  assert.match(source, /withLLMReasoningEffort\(selectedSelection, option\.value\)/);
  assert.match(source, /reasoning_effort/);
  assert.match(source, /Select reasoning effort/);
});

test("the reasoning control renders the active conversation override", () => {
  const html = renderModelSelector("xhigh");

  assert.match(html, /aria-label="Select reasoning effort"/);
  assert.match(html, /Extra high/);
});

test("the reasoning control hides when the model has no request levels", () => {
  const html = renderToStaticMarkup(
    React.createElement(ModelSelector, {
      options: [
        {
          ...reasoningModel,
          model: "claude-opus-5",
          supported_reasoning_levels: ["adaptive"],
        },
      ],
      activeDefault: {
        profile_id: reasoningModel.profile_id,
        model_id: reasoningModel.model_id,
      },
      value: {
        profile_id: reasoningModel.profile_id,
        model_id: reasoningModel.model_id,
      },
      loading: false,
      error: false,
      placement: "top",
      onChange: () => {},
    }),
  );

  assert.doesNotMatch(html, /Select reasoning effort/);
});
