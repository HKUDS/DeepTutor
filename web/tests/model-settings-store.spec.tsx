import React, { useEffect } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
  type Catalog,
} from "@/features/settings/store/SettingsStore";
import { modelTestFingerprint, modelTestKey } from "@/lib/model-settings";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  router: { push: vi.fn() },
}));
vi.mock("@/lib/api", () => ({
  apiUrl: (url: string) => url,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));
function translate(key: string) {
  return key;
}
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));
const shell = {
  codeBlockTheme: "github",
  codeBlockShowLineNumbers: true,
  codeBlockWrapLongLines: false,
  setCodeBlockTheme: vi.fn(),
  setCodeBlockShowLineNumbers: vi.fn(),
  setCodeBlockWrapLongLines: vi.fn(),
};
vi.mock("@/context/AppShellContext", () => ({ useAppShell: () => shell }));
vi.mock("@/lib/llm-options", () => ({
  invalidateLLMOptionsCache: vi.fn(),
}));

let settings: ReturnType<typeof useSettings>;
function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}
class Stream {
  static latest: Stream;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor() {
    Stream.latest = this;
  }
  emit(entry: object) {
    this.onmessage?.({ data: JSON.stringify(entry) });
  }
}
function fixture(): Catalog {
  const catalog = defaultCatalog();
  for (const service of ["llm", "task"] as const) {
    catalog.services[service] = {
      active_profile_id: `${service}-first`,
      active_model_id: `${service}-first-model`,
      profiles: ["first", "second"].map((name) => ({
        id: `${service}-${name}`,
        name,
        binding: "custom",
        base_url: "https://example.invalid/v1",
        api_key: "test-key",
        api_version: "",
        models: [
          {
            id: `${service}-${name}-model`,
            name,
            model: `${service}-${name}-model`,
          },
        ],
      })),
    };
  }
  return catalog;
}
function reply(payload: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: async () => payload };
}
let live: Catalog;
beforeEach(() => {
  live = fixture();
  vi.stubGlobal("EventSource", Stream);
  mocks.fetch.mockImplementation(async (url: string) => {
    if (url === "/api/settings")
      return reply({
        catalog: live,
        ui: { theme: "snow", language: "en" },
      });
    if (url === "/api/settings/draft") return reply({ draft: null });
    if (url.includes("/start")) return reply({ run_id: "run-one" });
    return reply({});
  });
});
async function mount() {
  render(
    <SettingsProvider>
      <Capture />
    </SettingsProvider>,
  );
  await waitFor(() => expect(settings.catalogEditable).toBe(true));
}

it("probes the addressed task model, keeps edits made during SSE, and ignores late events", async () => {
  await mount();
  await act(async () =>
    settings.runDetailedTest("task", {
      profileId: "task-second",
      modelId: "task-second-model",
    }),
  );
  const [, options] = mocks.fetch.mock.calls.find(([url]) =>
    String(url).includes("tests/task/start"),
  )!;
  const sent = JSON.parse(options.body).catalog;
  expect(sent.services.task.mode).toBe("profiles");
  expect(sent.services.task.active_model_id).toBe("task-second-model");
  expect(settings.draft.services.task.active_model_id).toBe(
    "task-first-model",
  );
  act(() =>
    settings.mutateCatalog((next) => {
      next.services.task.profiles[1].base_url =
        "https://changed.invalid/v1";
    }),
  );
  act(() => {
    Stream.latest.emit({
      type: "context_window",
      context_window: 128000,
      source: "metadata",
    });
    Stream.latest.emit({ type: "completed", message: "OK", catalog: live });
    Stream.latest.emit({ type: "failed", message: "Late stale event" });
  });
  const key = modelTestKey("task", "task-second", "task-second-model");
  expect(settings.modelTests[key].state).toBe("success");
  expect(settings.modelTests[key].fingerprint).not.toBe(
    modelTestFingerprint(
      settings.draft,
      "task",
      "task-second",
      "task-second-model",
    ),
  );
  expect(settings.draft.services.task.profiles[1].base_url).toBe(
    "https://changed.invalid/v1",
  );
  expect(
    settings.draft.services.task.profiles[1].models[0].context_window,
  ).toBeUndefined();
  expect(settings.testRunning).toBeNull();
  expect(Stream.latest.close).toHaveBeenCalledOnce();
});

it("saving rebases a successful test onto masked credentials without promoting other drafts", async () => {
  await mount();
  await act(async () =>
    settings.runDetailedTest("llm", {
      profileId: "llm-first",
      modelId: "llm-first-model",
    }),
  );
  act(() => Stream.latest.emit({ type: "completed", message: "OK" }));
  const masked = structuredClone(live);
  masked.services.llm.profiles[0].api_key = "***";
  let finish!: (value: unknown) => void;
  mocks.fetch.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  let saving!: Promise<boolean>;
  act(() => {
    saving = settings.saveProvider("llm", "llm-first");
  });
  act(() =>
    settings.mutateCatalog((next) => {
      next.services.task.profiles[0].name = "New unsaved task name";
    }),
  );
  await act(async () => {
    finish(reply({ catalog: masked, draft: null }));
    await saving;
  });
  expect(settings.draft.services.llm.profiles[0].api_key).toBe("***");
  expect(settings.draft.services.task.profiles[0].name).toBe(
    "New unsaved task name",
  );
  const key = modelTestKey("llm", "llm-first", "llm-first-model");
  expect(settings.modelTests[key].fingerprint).toBe(
    modelTestFingerprint(
      settings.draft,
      "llm",
      "llm-first",
      "llm-first-model",
    ),
  );
});

it("a failed provider save leaves every draft field intact and reports failure", async () => {
  await mount();
  act(() =>
    settings.mutateCatalog((next) => {
      next.services.llm.profiles[0].api_key = "unsaved-new-key";
    }),
  );
  const before = structuredClone(settings.draft);
  mocks.fetch.mockResolvedValueOnce(
    reply({ detail: "Cannot write settings" }, false),
  );
  let saved = true;
  await act(async () => {
    saved = await settings.saveProvider("llm", "llm-first");
  });
  expect(saved).toBe(false);
  expect(settings.draft).toEqual(before);
  expect(settings.catalog).toEqual(live);
  expect(settings.applying).toBe(false);
});

it("saving credentials for a retained task provider does not switch away from chat inheritance", async () => {
  live.services.task.mode = "inherit";
  await mount();
  mocks.fetch.mockResolvedValueOnce(reply({ catalog: live, draft: null }));
  await act(async () => {
    await settings.saveProvider("task", "task-first");
  });
  const [, options] = mocks.fetch.mock.calls.find(
    ([url]) => url === "/api/settings/apply/provider",
  )!;
  expect(JSON.parse(options.body).activate).toBe(false);
  expect(settings.draft.services.task.mode).toBe("inherit");
});
