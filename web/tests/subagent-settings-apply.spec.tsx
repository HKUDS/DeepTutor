import React, { useEffect } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { SettingsToolbar } from "@/components/settings/SettingsToolbar";
import { SubagentSettingsEditor } from "@/components/settings/SubagentSettingsEditor";
import { UiSettingsProvider } from "@/features/settings/store/UiSettingsProvider";

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
let subagents: {
  consult_budget: number;
  backends: Record<string, Record<string, unknown>>;
};
const reply = (value: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 422,
  json: async () => value,
});

const OPENCODE_OPTIONS = {
  kind: "opencode",
  display_name: "opencode",
  available: true,
  version: "0.6",
  default_model: "",
  models: [
    {
      slug: "gpt-5.2-codestop",
      display_name: "GPT-5.2 Codestop",
      default_effort: "high",
      efforts: ["low", "medium", "high"],
    },
    {
      slug: "restored-model",
      display_name: "Restored Model",
      default_effort: "high",
      efforts: ["low", "medium", "high"],
    },
  ],
  efforts: ["low", "medium", "high"],
  allow_custom_model: true,
  synced_at: "",
  detail: "",
};

beforeEach(() => {
  live = defaultCatalog();
  stored = null;
  subagents = { consult_budget: 5, backends: {} };
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/settings")
      return reply({
        catalog: live,
        ui: { theme: "snow", language: "en", response_language: "en" },
      });
    if (url === "/api/system/status") return reply({});
    if (url === "/api/subagents/backends/options")
      return reply({ backends: [OPENCODE_OPTIONS] });
    if (url === "/api/subagents/settings") {
      if (method === "PUT") {
        // Merge per backend and per field, like the real router does.
        const body = JSON.parse(String(init?.body)) as {
          consult_budget?: number;
          backends?: Record<string, Record<string, unknown>>;
        };
        if (typeof body.consult_budget === "number")
          subagents.consult_budget = body.consult_budget;
        for (const [kind, cfg] of Object.entries(body.backends ?? {})) {
          subagents.backends[kind] = {
            ...(subagents.backends[kind] ?? {}),
            ...(cfg ?? {}),
          };
        }
      }
      return reply(subagents);
    }
    if (url === "/api/settings/draft") {
      if (method === "PUT") stored = JSON.parse(String(init?.body));
      if (method === "DELETE") stored = null;
      return reply({ draft: stored });
    }
    if (url === "/api/settings/apply") {
      live = stored?.catalog ?? live;
      stored = null;
      return reply({ catalog: live });
    }
    return reply({});
  });
});

function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}

function App({ editor = true }: { editor?: boolean }) {
  return (
    <SettingsProvider>
      <UiSettingsProvider>
        <Capture />
        <SettingsToolbar />
        {editor ? <SubagentSettingsEditor kind="opencode" /> : null}
      </UiSettingsProvider>
    </SettingsProvider>
  );
}

async function ready() {
  await waitFor(() => expect(settings.settingsLoading).toBe(false));
}
const puts = (endpoint: string) =>
  mocks.fetch.mock.calls.filter(
    ([url, init]) => url === endpoint && init?.method === "PUT",
  );
const applyIndex = () =>
  mocks.fetch.mock.calls.findIndex(
    ([url, init]) => url === "/api/settings/apply" && init?.method === "POST",
  );

it("persists CLI-app model edits through Apply and keeps them after a reload (#1630)", async () => {
  const view = render(<App />);
  const model = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(model).toHaveValue(""));
  fireEvent.change(model, { target: { value: "gpt-5.2-codestop" } });
  await waitFor(() => expect(settings.draftState).toBe("unsaved"));
  expect(screen.getByText("Unsaved changes")).toBeTruthy();
  expect(puts("/api/subagents/settings")).toHaveLength(0);

  fireEvent.click(screen.getByText("Apply changes"));
  await waitFor(() => expect(settings.draftState).toBe("clean"));

  const writes = puts("/api/subagents/settings");
  expect(writes).toHaveLength(1);
  const body = JSON.parse(String(writes[0][1]?.body));
  expect(body.backends.opencode).toMatchObject({
    model: "gpt-5.2-codestop",
  });
  expect(writes[0][0]).toBe("/api/subagents/settings");
  expect(mocks.fetch.mock.calls.indexOf(writes[0])).toBeLessThan(applyIndex());
  expect(stored).toBeNull();
  expect(subagents.backends.opencode).toMatchObject({
    model: "gpt-5.2-codestop",
  });

  view.unmount();
  render(<App />);
  const reloaded = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(reloaded).toHaveValue("gpt-5.2-codestop"));
});

it("applies a parked subagent draft even when its editor is not mounted (#1630)", async () => {
  stored = {
    catalog: live,
    extensions: {
      "subagent:opencode": { enabled: true, model: "restored-model", effort: "high" },
    },
  };
  render(<App editor={false} />);
  await ready();
  await waitFor(() => expect(settings.draftState).toBe("saved"));
  expect(screen.getByText("Draft not applied yet")).toBeTruthy();

  fireEvent.click(screen.getByText("Apply changes"));
  await waitFor(() => expect(settings.draftState).toBe("clean"));

  const writes = puts("/api/subagents/settings");
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
    backends: { opencode: { enabled: true, model: "restored-model", effort: "high" } },
  });
  expect(mocks.fetch.mock.calls.indexOf(writes[0])).toBeLessThan(applyIndex());
  expect(stored).toBeNull();
  expect(subagents.backends.opencode).toEqual({
    enabled: true,
    model: "restored-model",
    effort: "high",
  });
});

it("restores a parked draft into the CLI-app editor, applies it, and keeps it after reload (#1630)", async () => {
  stored = {
    catalog: live,
    extensions: {
      "subagent:opencode": { enabled: true, model: "restored-model", effort: "high" },
    },
  };
  const view = render(<App />);
  const model = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(model).toHaveValue("restored-model"));
  await waitFor(() => expect(settings.draftState).toBe("saved"));

  fireEvent.click(screen.getByText("Apply changes"));
  await waitFor(() => expect(settings.draftState).toBe("clean"));
  expect(puts("/api/subagents/settings")).toHaveLength(1);
  expect(stored).toBeNull();

  view.unmount();
  render(<App />);
  const reloaded = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(reloaded).toHaveValue("restored-model"));
});
