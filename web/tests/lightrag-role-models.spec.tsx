import React, { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LightRagRoleModelsEditor, {
  newRoleModels,
  resolvedRole,
  roleModelsValidationError,
} from "@/components/knowledge/LightRagRoleModelsEditor";
import LightRagIndexingSelector, {
  indexingSelectionFromDefaults,
  indexingSelectionFromPolicy,
  isCompleteIndexingSelection,
} from "@/components/knowledge/LightRagIndexingSelector";
import type {
  LightRagRoleModels,
  LightRagIndexingSelection,
} from "@/features/knowledge/model/types";
import type { LLMOption } from "@/lib/llm-options";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));
const textModel = { profile_id: "text", model_id: "small" };
const visionModel = { profile_id: "vision", model_id: "large" };
const options: LLMOption[] = [
  {
    ...textModel,
    profile_name: "Text provider",
    model_name: "Small",
    model: "small",
    provider: "custom",
    supports_vision: false,
    supported_reasoning_efforts: ["none", "low"],
    is_active_default: true,
  },
  {
    ...visionModel,
    profile_name: "Vision provider",
    model_name: "Large",
    model: "large",
    provider: "custom",
    supports_vision: true,
    supported_reasoning_efforts: ["none", "high"],
    is_active_default: false,
  },
];
function Editor({
  initial = newRoleModels(textModel),
}: {
  initial?: LightRagRoleModels;
}) {
  const [models, setModels] = useState(initial);
  return (
    <>
      <LightRagRoleModelsEditor
        models={models}
        options={options}
        loading={false}
        error={false}
        onChange={setModels}
      />
      <output data-testid="models">{JSON.stringify(models)}</output>
    </>
  );
}
function state(): LightRagRoleModels {
  return JSON.parse(screen.getByTestId("models").textContent ?? "{}");
}

describe("LightRAG role editor", () => {
  it("keeps disabled, inherited, and explicit VLM choices distinct", () => {
    render(<Editor />);
    const vlm = within(screen.getByRole("group", { name: "VLM" }));
    const mode = vlm.getByRole("combobox", { name: "VLM Model" });
    expect(state().vlm.mode).toBe("disabled");
    expect(
      within(mode).getByRole("option", {
        name: "Inherit LightRAG base model · Small",
      }),
    ).toBeDisabled();
    fireEvent.change(mode, { target: { value: "vision:large" } });
    expect(resolvedRole(state(), "vlm")).toEqual(visionModel);
    fireEvent.change(mode, { target: { value: "disabled" } });
    expect(resolvedRole(state(), "vlm")).toBeNull();
  });
  it("rejects invalid role state before it reaches the API", () => {
    const invalidVlm = newRoleModels(textModel);
    invalidVlm.vlm.mode = "inherit";
    expect(roleModelsValidationError(invalidVlm, options)).toBe(
      "The selected VLM model does not support image inputs.",
    );
    const staleBase = newRoleModels({ profile_id: "gone", model_id: "gone" });
    expect(roleModelsValidationError(staleBase, options)).toBe(
      "The LightRAG base model is unavailable. Choose an accessible model.",
    );
    const invalidLimit = newRoleModels(textModel);
    invalidLimit.query.max_async = 0;
    expect(roleModelsValidationError(invalidLimit, options)).toBe(
      "Concurrency and timeout values must stay within the displayed limits.",
    );
    const invalidBaseReasoning = newRoleModels({
      ...textModel,
      reasoning_effort: "high",
    });
    expect(roleModelsValidationError(invalidBaseReasoning, options)).toBe(
      "The selected reasoning effort is no longer supported.",
    );
  });
  it("preserves explicit none and limits when the base model changes", () => {
    render(<Editor />);
    const extract = within(screen.getByRole("group", { name: "EXTRACT" }));
    fireEvent.click(extract.getByText("Advanced"));
    fireEvent.change(
      extract.getByRole("combobox", { name: "Reasoning effort" }),
      {
        target: { value: "none" },
      },
    );
    fireEvent.change(
      extract.getByRole("spinbutton", { name: "EXTRACT Timeout (seconds)" }),
      {
        target: { value: "321" },
      },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "LightRAG base model" }),
      {
        target: { value: "vision:large" },
      },
    );
    expect(resolvedRole(state(), "extract")).toEqual({
      ...visionModel,
      reasoning_effort: "none",
    });
    expect(state().extract.timeout).toBe(321);
    expect(state().vlm.mode).toBe("disabled");
  });
  it("shows concise role guidance and one model selector per role", () => {
    render(<Editor />);
    const extract = within(screen.getByRole("group", { name: "EXTRACT" }));
    expect(
      extract.getByText(
        "Used to extract entities and relationships during indexing. Choose a fast, economical model with reasoning disabled.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The default model when no role model is specified. Role models can inherit its model and reasoning setting.",
      ),
    ).toBeInTheDocument();
    expect(
      extract.getAllByRole("combobox", { name: "EXTRACT Model" }),
    ).toHaveLength(1);
    expect(
      within(screen.getByRole("group", { name: "VLM" })).getByText(
        "Used to analyze images during indexing. The model must support image input.",
      ),
    ).toBeInTheDocument();
  });
  it("shows an invalid saved effort without offering unsupported replacements", () => {
    const initial = newRoleModels(textModel);
    initial.extract.reasoning_effort = "high";
    render(<Editor initial={initial} />);
    const selector = within(
      screen.getByRole("group", { name: "EXTRACT" }),
    ).getByRole("combobox", {
      name: "Reasoning effort",
    });
    expect(
      within(selector).getByRole("option", {
        name: "Unsupported reasoning effort: high",
      }),
    ).toBeDisabled();
    expect(selector).toHaveValue("high");
    expect(
      within(selector).queryByRole("option", { name: "Max" }),
    ).not.toBeInTheDocument();
  });
});
it("prefills independent indexing roles and preserves a saved disabled policy", () => {
  const roles = newRoleModels(textModel);
  roles.vlm = {
    mode: "model",
    selection: visionModel,
    reasoning_effort: "none",
    max_async: 4,
    timeout: 240,
  };
  expect(
    indexingSelectionFromDefaults(
      options,
      { llm_profile_id: "old", llm_model_id: "old", role_models: roles },
      visionModel,
    ),
  ).toEqual({
    extract: textModel,
    vlm: {
      mode: "enabled",
      selection: { ...visionModel, reasoning_effort: "none" },
    },
  });
  expect(
    indexingSelectionFromPolicy({
      schema_version: 2,
      policy: "pending_pinned",
      extract: { policy: "pinned", selection: textModel },
      vlm: { mode: "disabled" },
    }),
  ).toEqual({ extract: textModel, vlm: { mode: "disabled" } });
});
it("selects a vision model without a duplicate VLM control", () => {
  function Draft() {
    const [selection, setSelection] =
      useState<LightRagIndexingSelection | null>({
        extract: textModel,
        vlm: { mode: "disabled" },
      });
    return (
      <>
        <LightRagIndexingSelector
          options={options}
          selection={selection}
          onChange={setSelection}
          loading={false}
          error={false}
        />
        <output data-testid="draft">{JSON.stringify(selection)}</output>
        <button disabled={!isCompleteIndexingSelection(selection)}>
          Submit
        </button>
      </>
    );
  }
  render(<Draft />);
  fireEvent.change(
    screen.getByRole("combobox", { name: "VLM image analysis" }),
    {
      target: { value: "vision:large" },
    },
  );
  expect(
    JSON.parse(screen.getByTestId("draft").textContent ?? "{}").vlm,
  ).toEqual({
    mode: "enabled",
    selection: visionModel,
  });
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  expect(
    screen.queryByRole("combobox", { name: "VLM model" }),
  ).not.toBeInTheDocument();
});

it("blocks structurally complete indexing selections whose models disappeared", () => {
  const stale: LightRagIndexingSelection = {
    extract: { profile_id: "gone", model_id: "gone" },
    vlm: { mode: "disabled" },
  };
  expect(isCompleteIndexingSelection(stale)).toBe(true);
  expect(isCompleteIndexingSelection(stale, options)).toBe(false);
  render(
    <LightRagIndexingSelector
      options={options}
      selection={stale}
      onChange={vi.fn()}
      loading={false}
      error={false}
    />,
  );
  expect(
    screen.getByText(
      "One or more selected indexing models are unavailable. Choose accessible models before continuing.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Unavailable model · gone" }),
  ).toBeDisabled();
});

it("shows engine defaults in the collapsed create-index summary", () => {
  const defaults: LightRagIndexingSelection = {
    extract: textModel,
    vlm: { mode: "disabled" },
  };
  render(
    <LightRagIndexingSelector
      options={options}
      selection={defaults}
      defaults={defaults}
      collapsible
      onChange={vi.fn()}
      loading={false}
      error={false}
    />,
  );
  expect(
    screen.getByText("EXTRACT: Small · VLM: Image analysis disabled"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("Indexing models (optional override)"));
  expect(
    screen.getByRole("combobox", { name: "EXTRACT model" }),
  ).toHaveValue("__engine_default__");
  expect(
    screen.getByRole("combobox", { name: "VLM image analysis" }),
  ).toHaveValue("__engine_default__");
});

it("distinguishes inherited reasoning from an explicit override with the same value", () => {
  render(
    <Editor
      initial={newRoleModels({ ...visionModel, reasoning_effort: "high" })}
    />,
  );
  const extract = within(screen.getByRole("group", { name: "EXTRACT" }));
  const reasoning = extract.getByRole("combobox", { name: "Reasoning effort" });
  expect(reasoning).toHaveValue("");
  expect(
    within(reasoning).getByRole("option", {
      name: "Inherit base reasoning",
      selected: true,
    }),
  ).toBeInTheDocument();
  expect(resolvedRole(state(), "extract")?.reasoning_effort).toBe("high");
  fireEvent.change(reasoning, { target: { value: "high" } });
  expect(reasoning).toHaveValue("high");
  fireEvent.change(
    screen.getAllByRole("combobox", { name: "Reasoning effort" })[0],
    { target: { value: "none" } },
  );
  expect(resolvedRole(state(), "extract")?.reasoning_effort).toBe("high");
  fireEvent.change(reasoning, { target: { value: "" } });
  expect(reasoning).toHaveValue("");
  expect(state().extract.reasoning_effort).toBeNull();
  expect(resolvedRole(state(), "extract")?.reasoning_effort).toBe("none");
});

it("prefills fresh indexing defaults with VLM disabled while preserving legacy vision defaults", () => {
  const defaults = { llm_profile_id: "", llm_model_id: "" };
  expect(
    indexingSelectionFromDefaults(
      options,
      { ...defaults, version: 2 },
      visionModel,
    )?.vlm,
  ).toEqual({ mode: "disabled" });
  expect(
    indexingSelectionFromDefaults(
      options,
      { ...defaults, version: 1 },
      visionModel,
    )?.vlm,
  ).toEqual({ mode: "enabled", selection: visionModel });
});
