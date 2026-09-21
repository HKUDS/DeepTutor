import React, { useEffect, useState } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { SettingsToolbar } from "@/components/settings/SettingsToolbar";
import DocumentParsing from "@/features/settings/sections/DocumentParsingSettingsSection";
import { MinerUEngineSettings } from "@/components/settings/MinerUEngineSettings";
import Appearance from "@/features/settings/sections/AppearanceSettingsSection";
import { UiSettingsProvider } from "@/features/settings/store/UiSettingsProvider";
import { stageRegistryAction } from "@/lib/provider-registry";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), theme: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("@/lib/theme", () => ({
  setTheme: (...args: unknown[]) => mocks.theme(...args),
}));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "github",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));
vi.mock("@/lib/llm-options", () => ({ invalidateLLMOptionsCache: vi.fn() }));
let settings: ReturnType<typeof useSettings>;
let live: ReturnType<typeof defaultCatalog>;
let stored: any;
let resources: Record<string, any>;
const reply = (value: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 422,
  json: async () => value,
});
beforeEach(() => {
  live = defaultCatalog();
  stored = null;
  resources = {
    workspace: { path: "/original" },
    "video-learning": { provider: "youtube" },
  };
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/settings")
      return reply({
        catalog: live,
        ui: { theme: "snow", language: "en", response_language: "en" },
      });
    if (url === "/api/settings/draft") {
      if (method === "PUT") stored = JSON.parse(String(init?.body));
      if (method === "DELETE") stored = null;
      return reply({ draft: stored });
    }
    if (url === "/api/settings/apply") {
      live = stored.catalog;
      stored = null;
      return reply({ catalog: live });
    }
    const key = url.split("/").pop()!;
    if (method === "PUT") resources[key] = JSON.parse(String(init?.body));
    return reply(resources[key] ?? {});
  });
});
function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}
function Editor({ name }: { name: string }) {
  const [liveValue, setLiveValue] = useState(resources[name]);
  const [draft, edit] = useStagedSettings(name, liveValue, setLiveValue);
  return (
    <input
      aria-label={name}
      value={draft.path ?? draft.provider}
      onChange={(e) =>
        edit(
          name === "workspace"
            ? { path: e.target.value }
            : { provider: e.target.value },
        )
      }
    />
  );
}
function App({ page = "workspace" }: { page?: string }) {
  return (
    <SettingsProvider>
      <UiSettingsProvider>
        <Capture />
        <SettingsToolbar />
        {page === "appearance" ? (
          <Appearance />
        ) : page === "document-parsing" ? (
          <DocumentParsing />
        ) : page === "mineru" ? (
          <MinerUEngineSettings />
        ) : page ? (
          <Editor key={page} name={page} />
        ) : null}
      </UiSettingsProvider>
    </SettingsProvider>
  );
}
async function ready() {
  await waitFor(() => expect(settings.settingsLoading).toBe(false));
}
const writes = (endpoint: string) =>
  mocks.fetch.mock.calls.filter(
    ([url, init]) => url === endpoint && init?.method === "PUT",
  );

it("keeps edits across pages, saves a real draft, and applies every page from one toolbar", async () => {
  const view = render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/draft" },
  });
  expect(writes("/api/settings/workspace")).toHaveLength(0);
  view.rerender(<App page="video-learning" />);
  fireEvent.change(screen.getByLabelText("video-learning"), {
    target: { value: "invidious" },
  });
  fireEvent.click(screen.getByText("Save draft"));
  await waitFor(() => expect(settings.draftState).toBe("saved"));
  expect(stored.extensions.workspace.path).toBe("/draft");
  expect(resources.workspace.path).toBe("/original");
  view.rerender(<App />);
  expect(screen.getByLabelText("workspace")).toHaveValue("/draft");
  fireEvent.click(screen.getByText("Apply changes"));
  await waitFor(() => expect(settings.draftState).toBe("clean"));
  expect(resources.workspace.path).toBe("/draft");
  expect(resources["video-learning"].provider).toBe("invidious");
  expect(stored).toBeNull();
});

it("restores a stored draft on remount, and Discard restores the live value without a write", async () => {
  const view = render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/draft" },
  });
  await act(() => settings.saveDraft());
  view.unmount();
  render(<App />);
  await ready();
  await waitFor(() =>
    expect(screen.getByLabelText("workspace")).toHaveValue("/draft"),
  );
  await act(() => settings.discardDraft());
  expect(screen.getByLabelText("workspace")).toHaveValue("/original");
  expect(writes("/api/settings/workspace")).toHaveLength(0);
});

it("keeps failed changes pending and allows retry", async () => {
  render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/invalid" },
  });
  const implementation = mocks.fetch.getMockImplementation()!;
  mocks.fetch.mockImplementation((url, init) =>
    url === "/api/settings/workspace"
      ? reply({ detail: "Invalid folder" }, false)
      : implementation(url, init),
  );
  await act(() => settings.applyCatalog());
  expect(settings.draftState).toBe("unsaved");
  expect(screen.getByLabelText("workspace")).toHaveValue("/invalid");
  expect(settings.toast).toContain("Could not apply");
  mocks.fetch.mockImplementation(implementation);
  await act(() => settings.applyCatalog());
  expect(settings.draftState).toBe("clean");
});

it("stages language and appearance without changing browser preferences until Apply", async () => {
  render(<App page="appearance" />);
  await ready();
  await act(async () => {
    await settings.updateTheme("dark");
    await settings.updateLanguage("zh");
    await settings.updateCodeBlockShowLineNumbers(true);
  });
  expect(settings.theme).toBe("dark");
  expect(settings.language).toBe("zh");
  expect(settings.codeBlockShowLineNumbers).toBe(true);
  expect(mocks.theme).not.toHaveBeenCalled();
  expect(writes("/api/settings/ui")).toHaveLength(0);
  await act(() => settings.discardDraft());
  expect(settings.theme).toBe("snow");
  await act(() => settings.updateTheme("dark"));
  await act(() => settings.applyCatalog());
  expect(mocks.theme).toHaveBeenCalledWith("dark");
  expect(resources.ui.theme).toBe("dark");
});

it("removes pending state when an edit is reverted", async () => {
  render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/draft" },
  });
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/original" },
  });
  expect(settings.draftState).toBe("clean");
});

it("stages default and task model choices against newly added draft models", async () => {
  render(<App page="" />);
  await ready();
  await act(async () =>
    settings.mutateCatalog((next) => {
      next.services.llm.profiles.push({
        id: "p",
        name: "new",
        binding: "custom",
        base_url: "",
        api_key: "",
        api_version: "",
        models: [{ id: "m", name: "m", model: "m" }],
      });
      stageRegistryAction(next, {
        kind: "default",
        service: "llm",
        profile_id: "p",
        model_id: "m",
      });
      stageRegistryAction(next, {
        kind: "task_choice",
        task: {
          mode: "reference",
          selection: { profile_id: "p", model_id: "m" },
        },
      });
    }),
  );
  expect(settings.draft.services.task.mode).toBe("reference");
  expect(live.services.llm.profiles).toHaveLength(0);
  await act(() => settings.applyCatalog());
  expect(live.services.llm.active_model_id).toBe("m");
  expect(live.services.task.selection?.model_id).toBe("m");
});

it("applies a restored draft while its editor is mounted without reverting the display", async () => {
  stored = {
    catalog: live,
    extensions: { workspace: { path: "/restored" } },
  };
  render(<App />);
  await ready();
  await waitFor(() =>
    expect(screen.getByLabelText("workspace")).toHaveValue("/restored"),
  );
  await act(() => settings.applyCatalog());
  expect(settings.draftState).toBe("clean");
  expect(screen.getByLabelText("workspace")).toHaveValue("/restored");
});

it("keeps the toolbar available when reverting an already saved draft", async () => {
  render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/draft" },
  });
  await act(() => settings.saveDraft());
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/original" },
  });
  expect(settings.draftState).toBe("unsaved");
  await act(() => settings.discardDraft());
  expect(stored).toBeNull();
  expect(settings.draftState).toBe("clean");
});

it("stages parser URL edits immediately and keeps them when changing parser panels", async () => {
  resources["document-parsing"] = {
    engine: "docling",
    engines: {
      docling: { mode: "remote", api_base_url: "http://parser-old" },
      tika: { server_url: "http://tika-old" },
      mineru: { mode: "local" },
    },
    available_engines: [
      { id: "docling", name: "Docling", available: true },
      { id: "tika", name: "Tika", available: true },
    ],
    readiness: {},
    installable: [],
    mineru: { api_token_set: false },
  };
  const view = render(<App page="document-parsing" />);
  await ready();
  fireEvent.change(await screen.findByDisplayValue("http://parser-old"), {
    target: { value: "http://parser-draft" },
  });
  expect(settings.draftState).toBe("unsaved");
  expect(writes("/api/settings/document-parsing")).toHaveLength(0);
  expect(
    screen.queryByRole("button", { name: "Save remote server" }),
  ).toBeNull();
  view.rerender(<App page="" />);
  await act(() => settings.applyCatalog());
  expect(resources["document-parsing"].engines.docling.api_base_url).toBe(
    "http://parser-draft",
  );
  expect(resources["document-parsing"].engines).not.toHaveProperty("mineru");
});

it("stages MinerU credentials and restores them when revisiting the page", async () => {
  resources.mineru = {
    settings: { mode: "cloud", api_base_url: "http://mineru" },
    api_token_set: false,
  };
  const view = render(<App page="mineru" />);
  await ready();
  fireEvent.change(await screen.findByPlaceholderText("Paste API token"), {
    target: { value: "test-only-token" },
  });
  expect(settings.draftState).toBe("unsaved");
  expect(writes("/api/settings/mineru")).toHaveLength(0);
  view.rerender(<App page="" />);
  view.rerender(<App page="mineru" />);
  expect(await screen.findByPlaceholderText("Paste API token")).toHaveValue(
    "test-only-token",
  );
  await act(() => settings.discardDraft());
  expect(screen.getByPlaceholderText("Paste API token")).toHaveValue("");
});

it("allows incomplete model drafts but blocks Apply before writing any live settings", async () => {
  render(<App />);
  await ready();
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/draft" },
  });
  await act(async () =>
    settings.mutateCatalog((next) => {
      next.services.llm.profiles.push({
        id: "new",
        name: "new",
        binding: "custom",
        api_key: "",
        api_version: "",
        base_url: "",
        models: [{ id: "new", name: "new", model: "" }],
      });
    }),
  );
  await act(() => settings.saveDraft());
  expect(stored.catalog.services.llm.profiles[0].models[0].model).toBe("");
  await act(() => settings.applyCatalog());
  expect(settings.draftState).toBe("saved");
  expect(writes("/api/settings/workspace")).toHaveLength(0);
  expect(live.services.llm.profiles).toHaveLength(0);
});
