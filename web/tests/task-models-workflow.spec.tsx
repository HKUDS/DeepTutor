import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type {
  Catalog,
  SettingsContextValue,
} from "@/features/settings/store/SettingsStore";
import { TaskModelsWorkspace } from "@/components/settings/TaskModelsWorkspace";

const mocks = vi.hoisted(() => ({
  settings: {} as SettingsContextValue,
  save: vi.fn(),
}));
vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => mocks.settings,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (s: string, args?: Record<string, unknown>) =>
      s.replace(/{{(\w+)}}/g, (_, name) => String(args?.[name] ?? name)),
  }),
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
    active_profile_id: "chat",
    active_model_id: "big",
    profiles: [
      {
        id: "chat",
        name: "My account",
        binding: "custom",
        api_key: "***",
        base_url: "https://example.test/v1",
        api_version: "",
        models: [{ id: "big", name: "Big", model: "model-big" }],
      },
    ],
  };
  services.task = {
    mode: "profiles",
    active_profile_id: "cheap",
    active_model_id: "mini",
    profiles: [
      {
        id: "cheap",
        name: "Task account",
        binding: "custom",
        api_key: "***",
        base_url: "https://example.test/v1",
        api_version: "",
        models: [
          { id: "mini", name: "Mini", model: "model-mini" },
          { id: "nano", name: "Nano", model: "model-nano" },
        ],
      },
    ],
  };
  return { version: 1, connections: [], services };
}

let live: Catalog;
function show(overrides: Record<string, unknown> = {}) {
  mocks.settings = {
    catalog: live,
    draft: structuredClone(live),
    catalogEditable: true,
    applying: false,
    modelTests: {},
    testRunning: null,
    taskKinds: [
      { id: "session_title", group: "chat" },
      { id: "chat_starters", group: "chat" },
      { id: "reading_translation", group: "reading" },
      { id: "reading_future_task", group: "reading" },
    ],
    connectionTargets: [],
    saveRegistry: mocks.save,
    mutateCatalog: (change: (draft: Catalog) => void) => change(mocks.settings.draft),
    runDetailedTest: vi.fn(),
    ...overrides,
  } as unknown as SettingsContextValue;
  return render(<TaskModelsWorkspace />);
}

beforeEach(() => {
  live = fixture();
  mocks.save.mockReset();
});

it("names each task and shows what it is running on, pin or global", () => {
  live.services.task.overrides = {
    session_title: {
      mode: "profiles",
      active_profile_id: "cheap",
      active_model_id: "nano",
    },
  };
  show();

  // The global choice and one pinned task read their own values; a task with no
  // record of its own says so rather than echoing the global model's name.
  expect(screen.getByLabelText("Background task model")).toHaveValue(
    "task:cheap:mini",
  );
  expect(screen.getByLabelText("Conversation titles")).toHaveValue(
    "task:cheap:nano",
  );
  expect(screen.getByLabelText("Starter suggestions")).toHaveValue("global");
  expect(screen.getByLabelText("Translation")).toHaveValue("global");
  // A task the backend added and this page has no wording for is still listed:
  // configuring a call DeepTutor makes matters before naming it does.
  expect(screen.getByLabelText("reading_future_task")).toHaveValue("global");
  expect(screen.getByRole("heading", { name: "Immersive reading" })).toBeTruthy();
});

it("stores a per-task pin against that task and clears it back to the global one", () => {
  show();
  fireEvent.change(screen.getByLabelText("Conversation titles"), {
    target: { value: "task:cheap:nano" },
  });
  expect(mocks.save).not.toHaveBeenCalled();
  expect(mocks.settings.draft.services.task.overrides?.session_title).toEqual({
      mode: "profiles",
      active_profile_id: "cheap",
      active_model_id: "nano",
  });

  // Following the global model is the absence of a pin, so clearing one is its
  // own edit rather than a fourth mode written into the row.
  fireEvent.change(screen.getByLabelText("Conversation titles"), {
    target: { value: "global" },
  });
  expect(mocks.settings.draft.services.task.overrides?.session_title).toBeUndefined();

  // A chat model is pointed at by reference, so moving that model later moves
  // the task with it instead of stranding a copied pointer.
  fireEvent.change(screen.getByLabelText("Translation"), {
    target: { value: "llm:chat:big" },
  });
  expect(mocks.settings.draft.services.task.overrides?.reading_translation).toEqual({
      mode: "reference",
      selection: { profile_id: "chat", model_id: "big" },
  });
  expect(live.services.task.overrides).toBeUndefined();
});

it("edits the global choice without naming a task, and can hand it back to the chat model", () => {
  show();
  fireEvent.change(screen.getByLabelText("Background task model"), {
    target: { value: "inherit" },
  });
  expect(mocks.settings.draft.services.task.mode).toBe("inherit");
  expect(live.services.task.mode).toBe("profiles");
  expect(mocks.save).not.toHaveBeenCalled();
});

it("parks a pointer at a deleted model on the default instead of showing a blank select", () => {
  live.services.task.overrides = {
    chat_starters: {
      mode: "profiles",
      active_profile_id: "cheap",
      active_model_id: "deleted",
    },
  };
  show();
  const select = screen.getByLabelText("Starter suggestions");
  expect(select).toHaveValue("global");
  expect(
    screen.getByRole("option", {
      name: "Selected model is unavailable — choose another",
    }),
  ).toBeDisabled();
  // Nothing is written until the reader picks: a stale pin is reported, not
  // silently rewritten by opening the page.
  expect(mocks.save).not.toHaveBeenCalled();
});

it("tells a non-admin the page is read-only instead of offering selects that cannot save", () => {
  show({ catalogEditable: false });
  expect(
    screen.getByText("Only administrators can manage models."),
  ).toBeVisible();
  expect(screen.queryByLabelText("Background task model")).toBeNull();
});
