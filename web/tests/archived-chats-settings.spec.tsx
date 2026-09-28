import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ArchivedChatsSettingsSection from "@/features/settings/sections/ArchivedChatsSettingsSection";
import type { SessionSummary } from "@/lib/session-api";

const fixture = vi.hoisted(() => ({
  sessions: [] as SessionSummary[],
  list: vi.fn(),
  remove: vi.fn(),
  organize: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: fixture.push }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "en" } }),
}));
function translate(key: string) {
  return key;
}
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({ activeSessionId: null, setActiveSessionId: vi.fn() }),
}));
vi.mock("@/lib/session-api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  listAllSessions: (...args: unknown[]) => fixture.list(...args),
  deleteSession: (...args: unknown[]) => fixture.remove(...args),
  updateSessionOrganization: (...args: unknown[]) => fixture.organize(...args),
}));
vi.mock("@/lib/learning-api", () => ({
  fetchMasteryTopicIndex: async () => [],
}));
vi.mock("@/lib/reading-workspace-api", () => ({
  fetchReadingCollectionIndex: async () => [],
}));

beforeEach(() => {
  fixture.sessions = [
    { session_id: "active", title: "Active chat", preferences: {} },
    {
      session_id: "archive-a",
      title: "Archived algebra",
      preferences: { archived: true },
    },
    {
      session_id: "archive-b",
      title: "Archived geometry",
      preferences: { archived: true },
    },
  ].map((row) => ({
    id: row.session_id,
    created_at: 1,
    updated_at: 1,
    message_count: 2,
    last_message: "",
    ...row,
  }));
  fixture.list.mockImplementation(async () => [...fixture.sessions]);
  fixture.remove.mockImplementation(async (id: string) => {
    fixture.sessions = fixture.sessions.filter((row) => row.session_id !== id);
  });
  fixture.organize.mockImplementation(async (id: string) => {
    fixture.sessions = fixture.sessions.map((row) =>
      row.session_id === id
        ? { ...row, preferences: { archived: false } }
        : row,
    );
  });
});

it("searches archived chats and restores one without touching active conversations", async () => {
  render(<ArchivedChatsSettingsSection />);
  await screen.findByText("Archived algebra");
  expect(screen.queryByText("Active chat")).toBeNull();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Search archived chats" }),
    { target: { value: "algebra" } },
  );
  expect(screen.queryByText("Archived geometry")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
  await waitFor(() =>
    expect(fixture.organize).toHaveBeenCalledWith("archive-a", {
      archived: false,
    }, ""),
  );
  await screen.findByText("No archived chats match your search.");
});

it("requires confirmation and bulk deletion still means all archives when searching", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ArchivedChatsSettingsSection />);
  await screen.findByText("Archived algebra");
  fireEvent.change(
    screen.getByRole("textbox", { name: "Search archived chats" }),
    { target: { value: "algebra" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  expect(fixture.remove).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Delete all archived chats" }),
  );
  await screen.findByText("Nothing is archived yet.");
  expect(fixture.remove.mock.calls.map(([id]) => id).sort()).toEqual([
    "archive-a",
    "archive-b",
  ]);
  expect(fixture.sessions.map((row) => row.session_id)).toEqual(["active"]);
});

it("keeps failed deletions visible and reports partial failure", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fixture.remove.mockImplementation(async (id: string) => {
    if (id === "archive-b") throw new Error("offline");
    fixture.sessions = fixture.sessions.filter((row) => row.session_id !== id);
  });
  render(<ArchivedChatsSettingsSection />);
  await screen.findByText("Archived algebra");
  fireEvent.click(
    screen.getByRole("button", { name: "Delete all archived chats" }),
  );
  await screen.findByRole("alert");
  await waitFor(() =>
    expect(screen.queryByText("Archived algebra")).toBeNull(),
  );
  expect(screen.getByText("Archived geometry")).toBeInTheDocument();
});

it("restores a record in its originating workspace from the account-wide archive", async () => {
  fixture.sessions[1].content_workspace_id = "ws_other";
  render(<ArchivedChatsSettingsSection />);
  await screen.findByText("Archived algebra");
  fireEvent.change(screen.getByRole("textbox", { name: "Search archived chats" }), { target: { value: "algebra" } });
  fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
  await waitFor(() => expect(fixture.organize).toHaveBeenCalledWith("archive-a", { archived: false }, "ws_other"));
});
