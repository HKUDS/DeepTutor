import React, { useState } from "react";
import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type {
  Catalog,
  SettingsContextValue,
} from "@/features/settings/store/SettingsStore";
import { ModelsWorkspace } from "@/components/settings/ModelsWorkspace";
import { ProvidersWorkspace } from "@/components/settings/ProvidersWorkspace";
import { RegistryProbe } from "@/components/settings/RegistryControls";
import {
  flattenModels,
  providerRegistry,
  providerProbeInput,
  reconcileRegistrySave,
  providerServiceSupport,
  updateProvider,
} from "@/lib/provider-registry";
import { AddProviderPanel } from "@/components/settings/AddProviderPanel";
import { modelTestFingerprint } from "@/lib/model-settings";

const mocks = vi.hoisted(() => ({
  settings: {} as SettingsContextValue,
  fetch: vi.fn(),
  save: vi.fn(),
}));
vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => mocks.settings,
}));
vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (s: string, args?: Record<string, unknown>) =>
      s.replace(/{{(\w+)}}/g, (_, name) => String(args?.[name] ?? name)),
  }),
}));
// The embedding editor mounts the knowledge-base usage panel, which fetches.
vi.mock("@/features/knowledge/api/engines", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getEmbeddingUsage: () => Promise.resolve([]),
}));
vi.mock("@/components/settings/CodexOAuthCard", () => ({
  CodexOAuthCard: () => <div>Codex sign-in</div>,
}));
vi.mock("@/components/settings/CodeBuddyAuthCard", () => ({
  CodeBuddyAuthCard: () => <div>CodeBuddy sign-in</div>,
}));
function fixture(): Catalog {
  const services = Object.fromEntries(
    [
      "llm",
      "task",
      "embedding",
      "search",
      "tts",
      "stt",
      "imagegen",
      "videogen",
    ].map((s) => [
      s,
      { active_profile_id: null, active_model_id: null, profiles: [] },
    ]),
  ) as unknown as Catalog["services"];
  services.llm = {
    active_profile_id: "legacy",
    active_model_id: "one",
    profiles: [
      {
        id: "legacy",
        name: "My account",
        binding: "custom",
        api_key: "***",
        base_url: "https://example.test/v1",
        api_version: "",
        models: [
          {
            id: "one",
            name: "One",
            model: "model-one",
            context_window: "64000",
          },
          {
            id: "two",
            name: "Two",
            model: "model-two",
            context_window: "128000",
          },
        ],
      },
    ],
  };
  services.search = {
    active_profile_id: "search",
    profiles: [
      {
        id: "search",
        name: "Search account",
        provider: "tavily",
        api_key: "***",
        base_url: "",
        api_version: "",
        models: [],
      },
    ],
  };
  return { version: 1, connections: [], services };
}
/** A vendor no service table vouches for, on a connection shared across pages. */
const xai = () => ({
  id: "x",
  name: "xAI",
  provider: "xai",
  api_key: "***",
  base_url: "https://api.x.ai/v1",
  api_version: "",
});
let live: Catalog;
const minimaxProviders: Partial<SettingsContextValue["providers"]> = {
  llm: [
    { value: "custom", label: "Custom", base_url: "" },
    { value: "custom_anthropic", label: "Custom (Anthropic API)", status: "legacy", api_formats: ["anthropic"], default_api_format: "anthropic" },
    {
      value: "minimax", label: "MiniMax", status: "supported",
      base_url: "https://api.minimax.io/v1",
      api_formats: ["auto", "openai_chat", "openai_responses", "anthropic"],
      default_api_format: "auto",
      base_urls: { auto: "https://api.minimax.io/v1", openai_chat: "https://api.minimax.io/v1", anthropic: "https://api.minimax.io/anthropic" },
    },
    {
      value: "minimax_anthropic", label: "MiniMax (Anthropic)", status: "legacy",
      base_url: "https://api.minimax.io/anthropic",
      api_formats: ["anthropic"], default_api_format: "anthropic",
    },
  ],
  tts: [{ value: "minimax", label: "MiniMax", base_url: "https://api.minimax.io/v1" }],
};
function Harness({
  page,
  providerOptions,
}: {
  page: "llm" | "embedding" | "search" | "multimodal" | "voice" | "providers";
  providerOptions?: Partial<SettingsContextValue["providers"]>;
}) {
  const [draft, setDraft] = useState(() => structuredClone(live));
  // The mocked `useSettings` has to see this render's draft, so the harness
  // publishes it on the way through rather than from an effect — by then the
  // component under test has already read the previous value.
  // eslint-disable-next-line react-hooks/immutability
  mocks.settings = {
    catalog: live,
    draft,
    catalogEditable: true,
    applying: false,
    modelTests: {},
    testRunning: null,
    providers: {
      llm: [{ value: "custom", label: "Custom", base_url: "" }],
      task: [],
      embedding: [],
      search: [{ value: "tavily", label: "Tavily", requires_api_key: true }],
      tts: [],
      stt: [],
      imagegen: [],
      videogen: [],
      ...providerOptions,
    },
    connectionTargets: [],
    mutateCatalog: (change: (c: Catalog) => void) =>
      setDraft((current) => {
        const next = structuredClone(current);
        change(next);
        return next;
      }),
    saveRegistry: mocks.save,
    runDetailedTest: vi.fn(),
  } as unknown as SettingsContextValue;
  return page === "providers" ? (
    <ProvidersWorkspace />
  ) : (
    <ModelsWorkspace page={page} />
  );
}
beforeEach(() => {
  live = fixture();
  mocks.fetch.mockReset();
  mocks.save.mockReset();
  window.history.replaceState(null, "", "/settings/llm");
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

it("offers one MiniMax vendor with protocol choices instead of legacy provider aliases", () => {
  render(<Harness page="providers" providerOptions={minimaxProviders} />);
  fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
  expect(screen.queryByRole("radio", { name: "MiniMax (Anthropic)" })).toBeNull();
  expect(screen.queryByRole("radio", { name: "Custom (Anthropic API)" })).toBeNull();
  fireEvent.change(screen.getByRole("searchbox", { name: "settings.providerServices.search" }), { target: { value: "MiniMax" } });
  expect(screen.getAllByRole("radio")).toHaveLength(1);
  fireEvent.click(screen.getByRole("radio", { name: "MiniMax" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(mocks.settings.draft.connections?.at(-1)).toMatchObject({ provider: "minimax", api_format: "auto", base_url: "" });
  const protocol = screen.getByRole("combobox", { name: "settings.providerServices.protocol" });
  expect(within(protocol).getByRole("option", { name: "OpenAI Chat Completions" })).toBeTruthy();
  expect(within(protocol).getByRole("option", { name: "Anthropic Messages" })).toBeTruthy();
});

it("switches MiniMax default endpoints and probes with the chosen protocol while preserving custom URLs", async () => {
  live.connections = [{ id: "minimax", name: "MiniMax account", provider: "minimax", source_service: "llm", api_key: "test-key", base_url: "", api_version: "", api_format: "auto" }];
  const stored = structuredClone(live);
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ status: "connected", models: [] }) });
  render(<Harness page="providers" providerOptions={minimaxProviders} />);
  fireEvent.click(screen.getByRole("button", { name: /MiniMax account/ }));
  const protocol = screen.getByLabelText("settings.providerServices.protocol");
  const url = screen.getByLabelText("Provider URL") as HTMLInputElement;
  expect(url.placeholder).toBe("https://api.minimax.io/v1");
  fireEvent.change(protocol, { target: { value: "anthropic" } });
  expect(url.placeholder).toBe("https://api.minimax.io/anthropic");
  expect(url.value).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "Test provider" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("settings.providerServices.catalogListed"));
  expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toMatchObject({ binding: "minimax", api_format: "anthropic", base_url: "https://api.minimax.io/anthropic" });
  fireEvent.change(protocol, { target: { value: "openai_chat" } });
  expect(url.placeholder).toBe("https://api.minimax.io/v1");
  fireEvent.change(url, { target: { value: "https://gateway.test/minimax" } });
  fireEvent.change(protocol, { target: { value: "anthropic" } });
  expect(url.value).toBe("https://gateway.test/minimax");
  fireEvent.click(screen.getByRole("button", { name: "Test provider" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("settings.providerServices.catalogListed"));
  expect(JSON.parse(mocks.fetch.mock.calls[1][1].body)).toMatchObject({ binding: "minimax", api_format: "anthropic", base_url: "https://gateway.test/minimax" });
  expect(mocks.settings.draft.services).toEqual(stored.services);
  expect(live).toEqual(stored);
});

it("keeps existing MiniMax Anthropic accounts and their models editable without changing identity", () => {
  const profile = live.services.llm.profiles[0];
  Object.assign(profile, { binding: "minimax_anthropic", base_url: "", api_format: "anthropic" });
  const stored = structuredClone(live);
  render(<Harness page="providers" providerOptions={minimaxProviders} />);
  fireEvent.click(screen.getByRole("button", { name: /My account/ }));
  expect((screen.getByLabelText("Provider URL") as HTMLInputElement).placeholder).toBe("https://api.minimax.io/anthropic");
  const protocol = screen.getByLabelText("settings.providerServices.protocol");
  expect(within(protocol).getAllByRole("option").map(o => o.textContent)).toEqual(["Anthropic Messages"]);
  fireEvent.click(screen.getByRole("button", { name: "Rename provider" }));
  fireEvent.change(screen.getByLabelText("Rename provider"), { target: { value: "Renamed MiniMax" } });
  expect(mocks.settings.draft.services.llm.profiles[0]).toEqual({ ...stored.services.llm.profiles[0], name: "Renamed MiniMax" });
  expect(live).toEqual(stored);
});

it("projects old accounts and models without rewriting stored data or combining accounts", () => {
  const before = structuredClone(live);
  expect(providerRegistry(live).map((p) => p.id)).toEqual([
    "llm:legacy",
    "search:search",
  ]);
  expect(flattenModels(live, ["llm"]).map((r) => r.model?.id)).toEqual([
    "one",
    "two",
  ]);
  expect(live).toEqual(before);
});
it("keeps a flat model list, shows the selected identity, and never exposes credentials in model pages", () => {
  render(<Harness page="llm" />);
  fireEvent.click(screen.getByRole("button", { name: /My account.*Two/ }));
  const editor = screen.getByRole("region", { name: "Model settings" });
  expect(within(editor).getByRole("heading", { name: "Two" })).toBeTruthy();
  expect(within(editor).getByLabelText("Model ID")).toHaveValue("model-two");
  expect(within(editor).getByLabelText("Context length (tokens)")).toHaveValue(
    128000,
  );
  expect(screen.queryByLabelText("API key")).toBeNull();
  expect(screen.queryByLabelText("Provider URL")).toBeNull();
  expect(mocks.settings.draft.services.llm.active_model_id).toBe("one");
  fireEvent.click(within(editor).getByRole("button", { name: "Rename model" }));
  fireEvent.change(
    within(editor).getByRole("textbox", { name: "Rename model" }),
    { target: { value: "My reasoning model" } },
  );
  fireEvent.blur(within(editor).getByLabelText("Rename model"));
  expect(
    within(editor).getByRole("heading", { name: "My reasoning model" }),
  ).toBeTruthy();
  expect(mocks.settings.draft.services.llm.profiles[0].models[1].id).toBe(
    "two",
  );
});
it("stages a new model and defaults its display name to the typed model ID", async () => {
  render(<Harness page="llm" />);
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  fireEvent.change(screen.getByLabelText("Configured provider"), {
    target: { value: "llm:legacy" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  const editor = screen.getByRole("region", { name: "Model settings" });
  fireEvent.change(within(editor).getByLabelText("Model ID"), {
    target: { value: "custom/model-id" },
  });
  expect(
    within(editor).getByRole("heading", { name: "custom/model-id" }),
  ).toBeTruthy();
  expect(within(editor).queryByRole("button", { name: "Save model" })).toBeNull();
  expect(mocks.save).not.toHaveBeenCalled();
  const added = mocks.settings.draft.services.llm.profiles.flatMap(p => p.models).find(m => m.model === "custom/model-id");
  expect(added).toMatchObject({ model: "custom/model-id", name: "custom/model-id", provider_ref: expect.objectContaining({ profile_id: "legacy" }) });
  expect(live.services.llm.profiles.flatMap(p => p.models).some(m => m.model === "custom/model-id")).toBe(false);
});
it("provider settings contain connections only and direct links to each model page", () => {
  window.history.replaceState(
    null,
    "",
    "/settings/connections?provider=llm%3Alegacy",
  );
  render(<Harness page="providers" />);
  const editor = screen.getByRole("region", { name: "Provider settings" });
  expect(within(editor).getByLabelText("API key")).toBeTruthy();
  expect(screen.queryByLabelText("Model ID")).toBeNull();
  expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  expect(
    within(editor).getByRole("link", { name: "Language models" }),
  ).toHaveAttribute("href", expect.stringContaining("/settings/llm?provider="));
  expect(
    within(editor).getByRole("button", { name: "Remove provider" }),
  ).toBeDisabled();
});
it("search is a flat engine configuration without a fake context or model ID", () => {
  render(<Harness page="search" />);
  fireEvent.click(
    screen.getByRole("button", { name: /Search account.*Search account/ }),
  );
  expect(screen.getByLabelText("Maximum results")).toHaveValue(5);
  expect(screen.queryByLabelText("Model ID")).toBeNull();
  expect(screen.queryByLabelText("Context length (tokens)")).toBeNull();
});
it("only offers search engines with a supported adapter", () => {
  live.connections = [xai()];
  render(<Harness page="search" />);
  fireEvent.click(screen.getByRole("button", { name: "Add search configuration" }));
  const select = screen.getByLabelText("Configured provider");
  expect(within(select).queryByRole("option", { name: "xAI" })).toBeNull();
  expect(within(select).getByRole("option", { name: "Search account" })).toBeTruthy();
});
it("offers unverified embedding providers after opting into custom integration", async () => {
  live.connections = [xai()];
  render(<Harness page="embedding" />);
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  const select = screen.getByLabelText("Configured provider");
  expect(within(select).queryByRole("option", { name: "xAI" })).toBeNull();
  fireEvent.click(screen.getByLabelText("settings.serviceConfig.custom"));
  expect(within(select).getByRole("option", { name: "xAI" })).toBeTruthy();
  fireEvent.change(select, { target: { value: "connection:x" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  const profile = mocks.settings.draft.services.embedding.profiles.at(-1)!;
  // `custom` is the OpenAI-compatible binding, whose embedding endpoint the
  // backend derives from the connection URL.
  expect(profile.models[0].provider_ref).toMatchObject({
    connection_id: "x",
    binding: "custom",
  });
  expect(
    screen.getByRole("region", { name: "Model connection test" }),
  ).toBeTruthy();
  // Let the editor's usage fetch land so its state update stays in this test.
  await waitFor(() => expect(screen.queryByText("Loading...")).toBeNull());
});
it("invalidates tests on referenced key changes but keeps them after unrelated model edits", () => {
  const model = live.services.llm.profiles[0].models[0];
  model.provider_ref = {
    service: "search",
    profile_id: "search",
    binding: "custom",
  };
  const before = modelTestFingerprint(live, "llm", "legacy", "one");
  live.services.llm.profiles[0].models[1].model = "changed-sibling";
  expect(modelTestFingerprint(live, "llm", "legacy", "one")).toBe(before);
  live.services.search.profiles[0].api_key = "rotated";
  expect(modelTestFingerprint(live, "llm", "legacy", "one")).not.toBe(before);
});
it("reconciles a single model save without overwriting sibling or later typing", () => {
  const submitted = structuredClone(live),
    current = structuredClone(live),
    saved = structuredClone(live);
  current.services.llm.profiles[0].models[1].model = "unsaved-sibling";
  saved.services.llm.profiles[0].models[0].name = "Saved name";
  const edit = {
    kind: "model" as const,
    service: "llm" as const,
    profile_id: "legacy",
    model: submitted.services.llm.profiles[0].models[0],
  };
  const next = reconcileRegistrySave(current, submitted, saved, edit);
  expect(next.services.llm.profiles[0].models[1].model).toBe("unsaved-sibling");
  expect(next.services.llm.profiles[0].models[0].name).toBe("Saved name");
  current.services.llm.profiles[0].models[0].name = "Typed during save";
  expect(
    reconcileRegistrySave(current, submitted, saved, edit).services.llm
      .profiles[0].models[0].name,
  ).toBe("Typed during save");
});
it("discards an in-flight discovery after switching provider credentials", async () => {
  let finish!: (v: unknown) => void;
  mocks.fetch.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const onResult = vi.fn();
  const view = render(
    <RegistryProbe
      input={{
        binding: "custom",
        base_url: "https://old.test",
        api_key: "old",
      }}
      onResult={onResult}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Test provider" }));
  view.rerender(
    <RegistryProbe
      input={{
        binding: "custom",
        base_url: "https://new.test",
        api_key: "new",
      }}
      onResult={onResult}
    />,
  );
  finish({
    ok: true,
    json: async () => ({ status: "connected", models: [{ id: "stale" }] }),
  });
  await waitFor(() =>
    expect(mocks.fetch.mock.calls[0][1].signal.aborted).toBe(true),
  );
  expect(onResult).not.toHaveBeenCalled();
});


it("sends the search proxy and explains JSON rejection from a Docker loopback address", async () => {
  const catalog = fixture();
  catalog.services.search.profiles = [{
    id: "search", name: "Local search", provider: "searxng",
    base_url: "http://localhost:8888", api_key: "", api_version: "",
    proxy: "http://proxy:3128", models: [],
  }];
  const source = providerRegistry(catalog).find(item => item.provider === "searxng")!;
  mocks.fetch.mockResolvedValue({
    ok: true,
    json: async () => ({ status: "json_forbidden", models: [], http_status: 403 }),
  });
  render(<RegistryProbe input={providerProbeInput(source)} onResult={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Test provider" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("search.formats"));
  expect(screen.getByRole("status").textContent).toContain("HTTP 403");
  expect(screen.getByRole("status").textContent).toContain("DeepTutor container");
  expect(JSON.parse(mocks.fetch.mock.calls[0][1].body).proxy).toBe("http://proxy:3128");
});

it("shows an empty search result as a reachable API with an engine warning", () => {
  render(<RegistryProbe
    input={{ service: "search", binding: "searxng", base_url: "http://localhost:8888" }}
    discovery={{ status: "connected", models: [], warning: "empty_results" }}
    onResult={() => {}}
  />);
  expect(screen.getByRole("status").textContent).toContain("Provider connected");
  expect(screen.getByRole("status").textContent).toContain("enabled engines");
  expect(screen.getByRole("status").textContent).not.toContain("DeepTutor container");
});

it.each([
  ["voice", ["tts", "stt"], ["imagegen", "videogen"], "Text-to-Speech", "Speech-to-Text"],
  ["multimodal", ["imagegen", "videogen"], ["tts", "stt"], "Image Generation", "Video Generation"],
] as const)("%s only lists and creates its own model types", (page, included, excluded, first, second) => {
  for (const service of ["tts", "stt", "imagegen", "videogen"] as const) {
    live.services[service].profiles = [{
      ...structuredClone(live.services.llm.profiles[0]),
      id: service,
      models: [{ id: service, model: `${service}-model`, name: `${service}-model` }],
    }];
  }
  render(<Harness page={page} />);
  for (const service of included) expect(screen.getAllByText(`${service}-model`).length).toBeGreaterThan(0);
  for (const service of excluded) expect(screen.queryByText(`${service}-model`)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  const select = screen.getByRole("combobox", { name: "Model type" });
  expect(within(select).getAllByRole("option").map(option => option.textContent)).toEqual([first, second]);
  expect((select as HTMLSelectElement).value).toBe(included[0]);
});


it("does not reinterpret old broad multimodal discovery as generation support", () => {
  render(<RegistryProbe
    input={{ binding: "custom", base_url: "https://example.test/v1", api_key: "", service: "llm" }}
    discovery={{ status: "connected", models: [], capabilities: [{ category: "multimodal", evidence: "metadata" }] }}
    onResult={() => {}}
  />);
  expect(screen.queryByText("Detected")).toBeNull();
  expect(screen.getByText("Voice")).toBeTruthy();
  expect(screen.getByText("Multimodal generation")).toBeTruthy();
});
it("adds a provider over plain HTTP, where crypto.randomUUID does not exist", () => {
  // `crypto.randomUUID` is secure-context-only, so a deployment reached over
  // plain HTTP (a LAN box, a VPS without TLS) has none. Minting the connection
  // id used to throw inside the click handler, before anything was staged, so
  // "Continue" did nothing at all and left nothing on screen to explain why.
  const webCrypto = globalThis.crypto as {
    randomUUID?: typeof globalThis.crypto.randomUUID;
  };
  const original = webCrypto?.randomUUID;
  if (webCrypto) webCrypto.randomUUID = undefined;
  try {
    render(<Harness page="providers" />);
    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    fireEvent.change(screen.getByLabelText("settings.providerServices.name"), { target: { value: "My gateway" } });
    fireEvent.change(screen.getByLabelText("Provider URL"), { target: { value: "http://gateway.test/v1" } });
    fireEvent.change(screen.getByLabelText("settings.providerServices.protocol"), { target: { value: "anthropic" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const staged = (mocks.settings.draft.connections ?? []).at(-1)!;
    expect(staged).toMatchObject({ provider: "custom", api_key: "", name: "My gateway", base_url: "http://gateway.test/v1", api_format: "anthropic" });
    expect(staged.id).toMatch(/^conn-[0-9a-f-]{36}$/);
    expect(
      screen.getByRole("region", { name: "Provider settings" }),
    ).toBeTruthy();
  } finally {
    if (webCrypto) webCrypto.randomUUID = original;
  }
});

it("enabling speech on a provider makes it selectable and keeps the chosen service adapter", () => {
  window.history.replaceState(null, "", "/settings/connections?provider=llm%3Alegacy");
  const view = render(<Harness page="providers" />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Text-to-Speech/ }));
  expect(mocks.settings.draft.services.llm.profiles[0].service_overrides?.tts).toEqual({ enabled: true, binding: "custom" });
  view.rerender(<Harness page="voice" />);
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  const select = screen.getByLabelText("Configured provider");
  expect(within(select).getByRole("option", { name: "My account" })).toBeTruthy();
  fireEvent.change(select, { target: { value: "llm:legacy" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(mocks.settings.draft.services.tts.profiles.at(-1)?.provider_ref).toMatchObject({ service: "llm", profile_id: "legacy", binding: "custom" });
});

it("keeps explicit disabled services out of new model choices even in custom mode", () => {
  live.services.llm.profiles[0].service_overrides = { tts: { enabled: false } };
  render(<Harness page="voice" />);
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  fireEvent.click(screen.getByLabelText("settings.serviceConfig.custom"));
  expect(within(screen.getByLabelText("Configured provider")).queryByRole("option", { name: "My account" })).toBeNull();
  expect(live.services.llm.profiles[0].models).toHaveLength(2);
});

it("uses live service metadata while manual choices survive reprobes and credential edits", () => {
  const source = providerRegistry(live)[0];
  source.source.discovery = { status: "connected", models: [], capabilities: [{ category: "tts", evidence: "metadata" }] };
  const providers = { llm: [], tts: [] } as unknown as SettingsContextValue["providers"];
  expect(providerServiceSupport(source, "tts", [], providers)).toEqual({ enabled: true, evidence: "detected" });
  updateProvider(live, source.ref, "service_overrides", { tts: { enabled: false }, stt: { enabled: true, binding: "custom" } });
  expect(source.source.discovery?.status).toBe("connected");
  expect(providerServiceSupport(source, "tts", [], providers)).toEqual({ enabled: false, evidence: "manual" });
  updateProvider(live, source.ref, "api_key", "rotated");
  expect(source.source.discovery).toBeUndefined();
  expect(providerServiceSupport(source, "stt", [], providers)).toEqual({ enabled: true, evidence: "manual" });
});

it("categorizes cross-service providers without duplicating accounts and supports search", () => {
  const props = { options: [
    { value: "a", label: "Aggregate", services: ["llm", "tts"] as const },
    { value: "b", label: "Search only", services: ["search"] as const },
    { value: "custom", label: "Custom", services: [] },
  ].map(p => ({ ...p, services: [...p.services] })), vendor: "", onVendor: vi.fn(), onCreate: vi.fn(), onCancel: vi.fn() };
  render(<AddProviderPanel {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "settings.providerServices.filter.multi" }));
  expect(screen.getByRole("radio", { name: "Aggregate" })).toBeTruthy();
  expect(screen.queryByRole("radio", { name: "Search only" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "settings.providerServices.filter.all" }));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Search only" } });
  expect(screen.getAllByRole("radio")).toHaveLength(1);
  expect(screen.getByRole("radio", { name: "Search only" })).toBeTruthy();
});

it("failed reprobes replace stale discovery instead of retaining a green capability result", async () => {
  mocks.fetch.mockRejectedValue(new Error("network"));
  const onResult = vi.fn();
  render(<RegistryProbe input={{ binding: "custom", base_url: "https://gateway.test/v1" }} discovery={{ status: "connected", models: [{ id: "old" }] }} onResult={onResult} />);
  fireEvent.click(screen.getByRole("button", { name: "Test provider" }));
  await waitFor(() => expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ status: "unreachable", models: [] })));
  expect(screen.queryByText("settings.providerServices.catalogListed")).toBeNull();
});
