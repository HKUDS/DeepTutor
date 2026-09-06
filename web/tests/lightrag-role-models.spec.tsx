import React, { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LightRagRoleModelsEditor, {
  newRoleModels,
  resolvedRole,
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
    const mode = vlm.getByRole("combobox", { name: "VLM Model source" });
    expect(state().vlm.mode).toBe("disabled");
    fireEvent.change(mode, { target: { value: "inherit" } });
    expect(
      vlm.getByText("The selected VLM model does not support image inputs."),
    ).toBeInTheDocument();
    expect(state().vlm.selection).toBeNull();
    fireEvent.change(mode, { target: { value: "model" } });
    fireEvent.change(
      vlm.getByRole("combobox", { name: "VLM effective model" }),
      {
        target: { value: "vision:large" },
      },
    );
    expect(resolvedRole(state(), "vlm")).toEqual(visionModel);
    fireEvent.change(mode, { target: { value: "disabled" } });
    expect(resolvedRole(state(), "vlm")).toBeNull();
  });
  it("preserves explicit none and limits when the base model changes", () => {
    render(<Editor />);
    const extract = within(screen.getByRole("group", { name: "EXTRACT" }));
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
it("requires an explicit vision selection when enabling it in a rebuild draft", () => {
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
      target: { value: "enabled" },
    },
  );
  expect(
    JSON.parse(screen.getByTestId("draft").textContent ?? "{}").vlm,
  ).toEqual({
    mode: "enabled",
  });
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "VLM model" }), {
    target: { value: "vision:large" },
  });
  expect(
    JSON.parse(screen.getByTestId("draft").textContent ?? "{}").vlm,
  ).toEqual({
    mode: "enabled",
    selection: visionModel,
  });
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
});
