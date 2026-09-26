import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentSettingsEditor } from "@/components/settings/SubagentSettingsEditor";
import {
  getBackendOptions,
  getSubagentSettings,
} from "@/lib/subagents-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "en" } }),
}));

const staged = vi.hoisted(() => {
  const payloads = new Map<string, unknown>();
  return {
    payloads,
    pendingExtensionPayload: (key: string) => payloads.get(key),
    registerExtension: vi.fn(
      (key: string, edit: { payload: unknown } | null) => {
        if (edit) payloads.set(key, edit.payload);
        else payloads.delete(key);
      },
    ),
  };
});

vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => ({
    applying: false,
    draftRevision: 0,
    pendingExtensionPayload: staged.pendingExtensionPayload,
    registerExtension: staged.registerExtension,
  }),
}));

vi.mock("@/lib/subagents-api", () => ({
  getBackendOptions: vi.fn(),
  getSubagentSettings: vi.fn(),
  syncBackendOptions: vi.fn(),
}));

beforeEach(() => {
  staged.payloads.clear();
  staged.registerExtension.mockClear();
  vi.mocked(getBackendOptions).mockResolvedValue([
    {
      kind: "grok",
      display_name: "Grok CLI",
      available: true,
      version: "installed",
      default_model: "",
      models: [],
      efforts: [],
      allow_custom_model: true,
      synced_at: "",
      detail: "",
    },
  ]);
  vi.mocked(getSubagentSettings).mockResolvedValue({
    consult_budget: 5,
    backends: {},
  });
});

describe("Grok CLI settings", () => {
  it("defaults to dontAsk and exposes only supported permission and input controls", async () => {
    render(<SubagentSettingsEditor kind="grok" />);

    const permissions = await screen.findByRole("combobox", {
      name: "Permission mode",
    });
    expect(permissions).toHaveValue("dontAsk");
    expect(
      within(permissions)
        .getAllByRole("option")
        .map((option) => (option as HTMLOptionElement).value),
    ).toEqual([
      "dontAsk",
      "plan",
      "default",
      "acceptEdits",
      "auto",
      "bypassPermissions",
    ]);
    expect(
      screen.getByRole("textbox", { name: "Reasoning effort" }),
    ).toBeEnabled();
    expect(screen.queryByText("Forward images")).not.toBeInTheDocument();
    expect(screen.queryByText("Auto-approve")).not.toBeInTheDocument();
    expect(staged.payloads.size).toBe(0);

    fireEvent.change(permissions, { target: { value: "plan" } });
    await waitFor(() =>
      expect(staged.payloads.get("subagent:grok")).toMatchObject({
        permission_mode: "plan",
      }),
    );
  });

  it("saves a manually entered model, effort, and rules without overwriting permissions", async () => {
    vi.mocked(getSubagentSettings).mockResolvedValue({
      consult_budget: 5,
      backends: { grok: { permission_mode: "plan" } },
    });
    const { rerender } = render(<SubagentSettingsEditor kind="grok" />);

    const modelSelector = await screen.findByRole("combobox", {
      name: "Model",
    });
    expect(within(modelSelector).getAllByRole("option")).toHaveLength(2);
    fireEvent.change(modelSelector, { target: { value: "__custom__" } });
    const model = screen.getByRole("textbox", { name: "Custom model" });
    fireEvent.change(model, { target: { value: " user-model " } });
    rerender(<SubagentSettingsEditor kind="grok" />);
    fireEvent.blur(model);
    await waitFor(() =>
      expect(staged.payloads.get("subagent:grok")).toMatchObject({
        model: "user-model",
        permission_mode: "plan",
      }),
    );
    rerender(<SubagentSettingsEditor kind="grok" />);

    const effort = screen.getByRole("textbox", { name: "Reasoning effort" });
    await waitFor(() => expect(effort).toBeEnabled());
    fireEvent.change(effort, { target: { value: " high " } });
    rerender(<SubagentSettingsEditor kind="grok" />);
    fireEvent.blur(effort);
    await waitFor(() =>
      expect(staged.payloads.get("subagent:grok")).toMatchObject({
        model: "user-model",
        effort: "high",
        permission_mode: "plan",
      }),
    );
    rerender(<SubagentSettingsEditor kind="grok" />);

    const rules = screen.getByRole("textbox", { name: "System prompt" });
    await waitFor(() => expect(rules).toBeEnabled());
    fireEvent.change(rules, {
      target: { value: "Check the textbook before explaining." },
    });
    rerender(<SubagentSettingsEditor kind="grok" />);
    fireEvent.blur(rules);
    await waitFor(() =>
      expect(staged.payloads.get("subagent:grok")).toMatchObject({
        model: "user-model",
        effort: "high",
        permission_mode: "plan",
        system_prompt: "Check the textbook before explaining.",
      }),
    );
    rerender(<SubagentSettingsEditor kind="grok" />);
    expect(
      screen.getByRole("combobox", { name: "Permission mode" }),
    ).toHaveValue("plan");
  });
});
