import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LightRagForm } from "@/features/knowledge/components/engines/EngineDetail";

const fixture = vi.hoisted(() => ({ version: 2, save: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({
    statusAvailable: true,
    enabled: false,
    isAdmin: true,
    loading: false,
  }),
}));
vi.mock("@/hooks/useLLMOptions", () => ({
  useLLMOptions: () => ({
    loading: false,
    error: false,
    activeDefault: { profile_id: "vision", model_id: "large" },
    options: [
      {
        profile_id: "vision",
        model_id: "large",
        profile_name: "Vision",
        model_name: "Large",
        model: "vision-large",
        provider: "custom",
        supports_vision: true,
        supported_reasoning_efforts: ["none", "high"],
      },
    ],
  }),
}));
vi.mock("@/features/knowledge/api/engines", async (original) => ({
  ...(await original<typeof import("@/features/knowledge/api/engines")>()),
  getLightRagConfig: async () => ({
    version: fixture.version,
    llm_profile_id: "",
    llm_model_id: "",
    top_k: 60,
    response_type: "Multiple Paragraphs",
    max_concurrent_files: 1,
    llm_model_max_async: 4,
    entity_extract_max_gleaning: 1,
  }),
  updateLightRagConfig: async (value: unknown) => {
    fixture.save(value);
    return value;
  },
}));
beforeEach(() => fixture.save.mockClear());

it.each([
  [2, "disabled"],
  [1, "inherit"],
] as const)(
  "saves version %s prefilled vision as %s",
  async (version, mode) => {
    fixture.version = version;
    render(<LightRagForm onChanged={vi.fn()} onError={vi.fn()} />);
    const vlm = within(await screen.findByRole("group", { name: "VLM" }));
    expect(vlm.getByRole("combobox", { name: "VLM Model source" })).toHaveValue(
      mode,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(fixture.save).toHaveBeenCalledOnce());
    expect(fixture.save.mock.calls[0][0].role_models).toMatchObject({
      base: { profile_id: "vision", model_id: "large" },
      vlm: { mode },
    });
  },
);
