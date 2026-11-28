import { describe, expect, it } from "vitest";

import {
  availableChoices,
  fallbackChoices,
  chainsEqual,
  sanitizeChain,
  withoutActive,
  type FallbackEntry,
} from "../features/settings/sections/models/fallback-chain";

const PROFILES = [
  {
    id: "deepseek",
    name: "DeepSeek",
    models: [
      { id: "ds-chat", name: "deepseek-chat", model: "deepseek-chat" },
      { id: "ds-reasoner", name: "deepseek-reasoner", model: "deepseek-reasoner" },
    ],
  },
  {
    id: "local",
    display_name: "Local vLLM",
    models: [{ id: "local-qwen", model: "qwen3-32b" }],
  },
  { id: "empty", models: [] },
];

const entry = (profile: string, model: string): FallbackEntry => ({
  profile_id: profile,
  model_id: model,
});

const emptyRow = (): FallbackEntry => ({ profile_id: "", model_id: "" });

describe("fallbackChoices", () => {
  it("offers every configured model with a readable label", () => {
    expect(fallbackChoices(PROFILES)).toEqual([
      { profileId: "deepseek", modelId: "ds-chat", label: "DeepSeek / deepseek-chat" },
      {
        profileId: "deepseek",
        modelId: "ds-reasoner",
        label: "DeepSeek / deepseek-reasoner",
      },
      { profileId: "local", modelId: "local-qwen", label: "Local vLLM / qwen3-32b" },
    ]);
  });

  it("ignores profiles without models", () => {
    expect(fallbackChoices([{ id: "empty", models: [] }])).toEqual([]);
  });
});

describe("sanitizeChain", () => {
  const choices = fallbackChoices(PROFILES);

  it("drops entries that no longer exist and collapses duplicates", () => {
    expect(
      sanitizeChain(
        [
          entry("local", "local-qwen"),
          entry("gone", "missing"),
          entry("local", "local-qwen"),
          entry("deepseek", "ds-chat"),
        ],
        choices,
      ),
    ).toEqual([entry("local", "local-qwen"), entry("deepseek", "ds-chat")]);
  });

  it("caps the chain at four candidates", () => {
    const many = Array.from({ length: 6 }, (_, index) =>
      entry("deepseek", `model-${index}`),
    );
    const padded = fallbackChoices([
      {
        id: "deepseek",
        models: many.map((_, index) => ({ id: `model-${index}` })),
      },
    ]);

    expect(sanitizeChain(many, padded)).toHaveLength(4);
  });
});

describe("availableChoices", () => {
  const choices = fallbackChoices(PROFILES);

  it("hides pairs already chosen by the other rows", () => {
    const rows = [entry("deepseek", "ds-chat"), emptyRow()];

    expect(availableChoices(choices, rows, 1)).toEqual([
      {
        profileId: "deepseek",
        modelId: "ds-reasoner",
        label: "DeepSeek / deepseek-reasoner",
      },
      { profileId: "local", modelId: "local-qwen", label: "Local vLLM / qwen3-32b" },
    ]);
  });

  it("keeps the row's own value even if another row duplicates it", () => {
    // Only an older payload can hold a duplicate; the select must still show it.
    const rows = [entry("deepseek", "ds-chat"), entry("deepseek", "ds-chat")];

    expect(availableChoices(choices, rows, 1).map((choice) => choice.modelId)).toContain(
      "ds-chat",
    );
  });
});

describe("withoutActive", () => {
  it("removes the active model so it is not its own fallback", () => {
    expect(
      withoutActive([entry("deepseek", "ds-chat"), entry("local", "local-qwen")], {
        profile_id: "deepseek",
        model_id: "ds-chat",
      }),
    ).toEqual([entry("local", "local-qwen")]);
  });

  it("is a no-op when there is no active selection", () => {
    const chain = [entry("local", "local-qwen")];
    expect(withoutActive(chain, null)).toEqual(chain);
  });
});

describe("chainsEqual", () => {
  it("compares order, not just membership", () => {
    const a = [entry("local", "local-qwen"), entry("deepseek", "ds-chat")];
    const b = [entry("deepseek", "ds-chat"), entry("local", "local-qwen")];

    expect(chainsEqual(a, a)).toBe(true);
    expect(chainsEqual(a, b)).toBe(false);
  });
});
