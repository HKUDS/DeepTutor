import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  detachProfileConnection,
  reconcileProviderSave,
  providerGroups,
  addDiscoveredModels,
  modelTestFingerprint,
  modelTestKey,
} from "@/lib/model-settings";
import type { Catalog } from "@/features/settings/store/SettingsStore";
import { ModelTestPanel } from "@/components/settings/ModelTestPanel";
import { ProviderModelDiscovery } from "@/components/settings/ProviderModelDiscovery";

const mocks = vi.hoisted(() => ({ settings: {} as any, fetch: vi.fn() }));
vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => mocks.settings,
}));
vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
  apiUrl: (url: string) => url,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: any) =>
      key.replace(/{{(\w+)}}/g, (_, name) => String(args?.[name] ?? name)),
  }),
}));
function fixture(): Catalog {
  const profiles = ["one", "two"].map((id) => ({
    id,
    name: "Same vendor",
    binding: "custom",
    base_url: "https://example.invalid/v1",
    api_key: "***",
    api_version: "",
    models: [
      {
        id: `${id}-model`,
        name: "Saved name",
        model: `${id}-model`,
        context_window: "65536",
        future: "keep",
      },
    ],
  }));
  return {
    version: 1,
    connections: [],
    services: Object.fromEntries(
      [
        "llm",
        "task",
        "embedding",
        "search",
        "tts",
        "stt",
        "imagegen",
        "videogen",
      ].map((service) => [
        service,
        {
          active_profile_id: service === "llm" ? "one" : null,
          active_model_id: service === "llm" ? "one-model" : null,
          profiles: service === "llm" ? profiles : [],
        },
      ]),
    ),
  } as unknown as Catalog;
}

describe("provider/model settings", () => {
  it("projects old providers without merging accounts or changing any persisted fields", () => {
    const catalog = fixture();
    const before = structuredClone(catalog);
    const groups = providerGroups(catalog);
    expect(groups.map((group) => group.id)).toEqual(["llm:one", "llm:two"]);
    expect(catalog).toEqual(before);
    const profile = catalog.services.llm.profiles[0];
    addDiscoveredModels(profile, ["one-model", "new-model", "new-model"]);
    expect(profile.models).toHaveLength(2);
    expect(profile.models[0]).toEqual(
      before.services.llm.profiles[0].models[0],
    );
    expect(catalog.services.llm.active_model_id).toBe("one-model");
  });

  it("preserves new typing, unrelated drafts and selection while a provider save completes", () => {
    const submitted = fixture();
    submitted.services.llm.profiles[0].api_key = "new-secret";
    const live = structuredClone(submitted);
    live.services.llm.profiles[0].api_key = "***";
    const edited = structuredClone(submitted);
    edited.services.llm.profiles[1].name = "Unsaved other account";
    edited.services.llm.active_profile_id = "two";
    edited.services.llm.active_model_id = "two-model";
    const normalized = reconcileProviderSave(
      edited,
      submitted,
      live,
      "llm",
      "one",
    );
    expect(normalized.services.llm.profiles[0].api_key).toBe("***");
    expect(normalized.services.llm.profiles[1].name).toBe(
      "Unsaved other account",
    );
    expect(normalized.services.llm.active_profile_id).toBe("two");
    edited.services.llm.profiles[0].models[0].model = "typed-during-save";
    expect(
      reconcileProviderSave(edited, submitted, live, "llm", "one"),
    ).toEqual(edited);
    edited.services.llm.profiles.shift();
    expect(
      reconcileProviderSave(edited, submitted, live, "llm", "one"),
    ).toEqual(edited);
  });

  it("discards a provider probe after its address changes, including a late response", async () => {
    let finish!: (value: unknown) => void;
    mocks.fetch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const onPickMany = vi.fn();
    const view = render(
      <ProviderModelDiscovery
        input={{ binding: "custom", base_url: "https://old.invalid" }}
        onPickMany={onPickMany}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Test provider connection" }),
    );
    view.rerender(
      <ProviderModelDiscovery
        input={{ binding: "custom", base_url: "https://new.invalid" }}
        onPickMany={onPickMany}
      />,
    );
    await act(async () =>
      finish({
        ok: true,
        json: async () => ({
          status: "connected",
          models: [{ id: "stale-model" }],
        }),
      }),
    );
    expect(screen.queryByText("stale-model")).toBeNull();
    expect(onPickMany).not.toHaveBeenCalled();
  });

  it("keeps newly entered shared credentials when switching to an independent provider", () => {
    const catalog = fixture();
    catalog.connections = [
      {
        id: "shared",
        name: "Shared",
        provider: "custom",
        api_key: "new-key",
        base_url: "https://new.invalid/v1",
        api_version: "v2",
        extra_headers: { "X-Account": "new-header" },
      },
    ];
    const profile = catalog.services.llm.profiles[0];
    profile.connection_id = "shared";
    detachProfileConnection(catalog, "llm", profile);
    expect(profile.connection_id).toBeUndefined();
    expect(profile.api_key).toBe("new-key");
    expect(profile.base_url).toBe("https://new.invalid/v1");
    expect(profile.extra_headers).toEqual({ "X-Account": "new-header" });
    expect(profile.models[0].context_window).toBe("65536");
    expect(catalog.connections).toHaveLength(1);
  });

  it("tests the inactive model on screen and applies metadata to that model only", () => {
    const draft = fixture();
    const profile = draft.services.llm.profiles[1];
    const model = profile.models[0];
    const run = vi.fn();
    const key = modelTestKey("llm", profile.id, model.id);
    mocks.settings = {
      draft,
      modelTests: {},
      testRunning: null,
      runDetailedTest: run,
      mutateCatalog: (edit: any) => edit(draft),
    };
    const view = render(
      <ModelTestPanel service="llm" profile={profile} model={model} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Test model" }));
    expect(run).toHaveBeenCalledWith("llm", {
      profileId: "two",
      modelId: "two-model",
    });
    mocks.settings.modelTests[key] = {
      state: "success",
      fingerprint: modelTestFingerprint(draft, "llm", profile.id, model.id),
      message: "OK",
      logs: "response OK",
      context: { value: 128000, source: "metadata" },
    };
    view.rerender(
      <ModelTestPanel service="llm" profile={profile} model={model} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Use detected value" }),
    );
    expect(model.context_window).toBe("128000");
    expect(draft.services.llm.profiles[0].models[0].context_window).toBe(
      "65536",
    );
    expect(draft.services.llm.active_profile_id).toBe("one");
    profile.base_url = "https://changed.invalid/v1";
    view.rerender(
      <ModelTestPanel service="llm" profile={profile} model={model} />,
    );
    expect(screen.queryByText("Model responded successfully")).toBeNull();
    expect(
      screen.getByText(
        "Settings changed since the last test. Test again to verify them.",
      ),
    ).toBeVisible();
  });

  it("adds multiple discovered models without replacing already configured models", async () => {
    mocks.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "connected",
        models: [{ id: "existing" }, { id: "new-a" }, { id: "new-b" }],
      }),
    });
    const onPickMany = vi.fn();
    render(
      <ProviderModelDiscovery
        input={{
          binding: "custom",
          base_url: "https://example.invalid/v1",
          api_key: "test-key",
        }}
        selectedModels={["existing"]}
        onPickMany={onPickMany}
      />,
    );
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Test provider connection" }),
      ),
    );
    expect(
      screen.getByRole("checkbox", { name: /existing/ }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "new-a" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "new-b" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Add selected models" }),
    );
    expect(onPickMany).toHaveBeenCalledWith(["new-a", "new-b"]);
  });
});
