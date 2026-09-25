import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PartnerArchives from "@/components/partners/PartnerArchives";
import { initializePartnerSessionKey, loadPartnerSessionKey, persistPartnerSessionKey } from "@/lib/partner-session";

const api = vi.hoisted(() => ({
  sessions: vi.fn(),
  historyPage: vi.fn(),
  resume: vi.fn(),
  remove: vi.fn(),
}));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock("@/lib/partners-api", () => ({
  getPartnerSessions: api.sessions,
  getPartnerHistoryPage: api.historyPage,
  resumePartnerSession: api.resume,
  deletePartnerSession: api.remove,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  api.sessions.mockResolvedValue([
    {
      session_key: "web-old-local",
      title: "Old browser conversation",
      archived: false,
      message_count: 121,
      updated_at: "2026-09-23T10:00:00",
      last_message: "newer",
    },
    {
      session_key: "web-archived",
      title: "Archived conversation",
      archived: true,
      message_count: 1,
      updated_at: "2026-09-22T10:00:00",
      last_message: "older",
    },
  ]);
  api.historyPage.mockImplementation(async (_partner: string, key: string, options: { before?: number }) => {
    if (key === "web-archived") {
      return { messages: [{ role: "user", content: "older" }], next_before: null };
    }
    return options.before === 1
      ? { messages: [{ role: "user", content: "beginning" }], next_before: null }
      : { messages: [{ role: "assistant", content: "newer" }], next_before: 1 };
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps non-archived browser conversations selectable and loads their beginning", async () => {
  const onResume = vi.fn();
  render(
    <PartnerArchives partnerId="ada" onToast={vi.fn()} onResume={onResume} />,
  );
  expect((await screen.findAllByText("Old browser conversation")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Archived conversation").length).toBeGreaterThan(0);
  expect((await screen.findAllByText("newer")).length).toBeGreaterThan(0);

  fireEvent.click(await screen.findByRole("button", { name: "Load older messages" }));
  expect(await screen.findByText("beginning")).toBeInTheDocument();
  expect(api.historyPage).toHaveBeenCalledWith("ada", "web-old-local", {
    before: 1,
    limit: 100,
  });

  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(onResume).toHaveBeenCalledWith("web-old-local", null, false));
  expect(api.resume).not.toHaveBeenCalled();
});

it("rotates the selected shared key when its conversation is deleted", async () => {
  api.remove.mockResolvedValue({ active_session_key: "web-replacement" });
  const onDeleted = vi.fn();
  render(
    <PartnerArchives
      partnerId="ada"
      onToast={vi.fn()}
      onDeleted={onDeleted}
    />,
  );
  await screen.findAllByText("Old browser conversation");
  fireEvent.click(screen.getByRole("button", { name: "Delete conversation" }));
  await waitFor(() =>
    expect(onDeleted).toHaveBeenCalledWith("web-old-local", "web-replacement"),
  );
});

it("stores browser-local keys separately for each account and partner", () => {
  persistPartnerSessionKey("ada", "web-alice", "alice");
  persistPartnerSessionKey("ada", "web-bob", "bob");
  persistPartnerSessionKey("bea", "web-other-partner", "alice");
  expect(loadPartnerSessionKey("ada", "alice")).toBe("web-alice");
  expect(loadPartnerSessionKey("ada", "bob")).toBe("web-bob");
  expect(loadPartnerSessionKey("bea", "alice")).toBe("web-other-partner");
});

it("migrates an old key only when ownership is provable", async () => {
  persistPartnerSessionKey("ada", "web-legacy");
  const owned = await initializePartnerSessionKey(
    "ada", "alice", { enabled: true, isAdmin: false, statusAvailable: true },
    async () => ["web-legacy"],
  );
  expect(owned).toBe("web-legacy");
  const other = await initializePartnerSessionKey(
    "ada", "bob", { enabled: true, isAdmin: false, statusAvailable: true },
    async () => [],
  );
  expect(other).not.toBe("web-legacy");
  const admin = await initializePartnerSessionKey(
    "ada", "admin", { enabled: true, isAdmin: true, statusAvailable: true },
    async () => ["web-legacy"],
  );
  expect(admin).not.toBe("web-legacy");
  const localAdmin = await initializePartnerSessionKey(
    "ada", "local-admin", { enabled: false, isAdmin: true, statusAvailable: true },
    async () => [],
  );
  expect(localAdmin).toBe("web-legacy");
});
