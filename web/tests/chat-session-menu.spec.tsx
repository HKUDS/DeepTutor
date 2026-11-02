import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import ChatSessionMenu from "@/features/chat/components/ChatSessionMenu";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

const api = vi.hoisted(() => ({
  updateSessionOrganization: vi.fn(),
  deleteSession: vi.fn(),
}));
vi.mock("@/lib/session-api", () => api);
vi.mock("@/lib/notifications", () => ({ notify: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  api.updateSessionOrganization.mockReset();
  api.deleteSession.mockReset();
});

const workspace: ChatWorkspaceRegistration = {
  workspace_id: "algebra",
  display_name: "Algebra",
  kind: "workspace",
  status: "ready",
  archived: false,
  follows_root: true,
  path: "/algebra",
  error: "",
  created_at: "",
};

function show(overrides: Partial<Parameters<typeof ChatSessionMenu>[0]> = {}) {
  const props = {
    sessionId: "chat-1",
    workspaceId: "algebra",
    row: {
      session_id: "chat-1",
      title: "Learning algebra",
      preferences: { workspace_id: "algebra" },
    },
    title: "Learning algebra",
    workspaces: [workspace],
    live: false,
    canSave: true,
    onSave: vi.fn(),
    canExport: false,
    onExport: vi.fn(),
    onRename: vi.fn(),
    onOrganized: vi.fn(),
    onMoved: vi.fn(),
    onDeleted: vi.fn(),
    ...overrides,
  };
  render(<ChatSessionMenu {...props} />);
  return props;
}

const trigger = () => screen.getByRole("button", { name: "Conversation actions" });

it("waits for a conversation before offering its actions", () => {
  show({ sessionId: null, row: null });
  expect(trigger()).toBeDisabled();
});

it("acts on the open conversation like its sidebar row, plus save and export", async () => {
  const updated = { session_id: "chat-1", title: "Learning algebra", preferences: { pinned: true } };
  api.updateSessionOrganization.mockResolvedValue(updated);
  const props = show();

  fireEvent.click(trigger());
  expect(trigger()).toHaveAttribute("aria-expanded", "true");
  for (const name of ["Rename chat", "Pin", "Archive", "General workspace", "Algebra", "Delete chat"]) {
    expect(screen.getByRole("menuitem", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("menuitem", { name: "Save to Notebook" })).toBeEnabled();
  expect(screen.getByRole("menuitem", { name: "Download Markdown" })).toBeDisabled();

  await act(async () => {
    fireEvent.click(screen.getByRole("menuitem", { name: "Pin" }));
  });
  expect(api.updateSessionOrganization).toHaveBeenCalledWith("chat-1", { pinned: true }, "algebra");
  expect(props.onOrganized).toHaveBeenCalledWith(updated);
  expect(screen.queryByRole("menu")).toBeNull();

  fireEvent.click(trigger());
  fireEvent.click(screen.getByRole("menuitem", { name: "Rename chat" }));
  expect(props.onRename).toHaveBeenCalled();
});

it("asks before deleting, then leaves the conversation", async () => {
  api.deleteSession.mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm");
  const props = show();

  confirm.mockReturnValueOnce(false);
  fireEvent.click(trigger());
  fireEvent.click(screen.getByRole("menuitem", { name: "Delete chat" }));
  expect(api.deleteSession).not.toHaveBeenCalled();

  confirm.mockReturnValueOnce(true);
  fireEvent.click(trigger());
  await act(async () => {
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete chat" }));
  });
  expect(api.deleteSession).toHaveBeenCalledWith("chat-1", "algebra");
  expect(props.onDeleted).toHaveBeenCalled();
});

it("keeps a running conversation where it is", () => {
  show({ live: true });
  fireEvent.click(trigger());
  expect(screen.getByRole("menuitem", { name: "General workspace" })).toBeDisabled();
  expect(screen.getByRole("menuitem", { name: "Algebra" })).toBeDisabled();
});

it("closes on Escape without letting the press reach the viewer panel", () => {
  const panelEscape = vi.fn();
  document.addEventListener("keydown", panelEscape);
  show();
  fireEvent.click(trigger());
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(panelEscape).not.toHaveBeenCalled();
  document.removeEventListener("keydown", panelEscape);
});
