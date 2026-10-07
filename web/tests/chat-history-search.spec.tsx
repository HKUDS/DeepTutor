import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ChatHistorySection from "@/components/space/ChatHistorySection";
import { searchAllSessions, updateSessionOrganization } from "@/lib/session-api";

const searchMock = vi.mocked(searchAllSessions);

const fixture = vi.hoisted(() => ({
  calls: [] as Array<{ query: string; signal?: AbortSignal }>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    activeSessionId: null,
    setActiveSessionId: vi.fn(),
  }),
}));
vi.mock("@/lib/workspace-scope", () => ({
  navigateTask: vi.fn(),
}));
vi.mock("@/lib/learning-api", () => ({
  fetchMasteryTopicIndex: vi.fn(async () => []),
}));
vi.mock("@/lib/reading-workspace-api", () => ({
  fetchReadingCollectionIndex: vi.fn(async () => []),
}));
vi.mock("@/lib/session-archive", () => ({
  collectArchivedConversations: vi.fn(() => ({ groups: [] })),
}));
vi.mock("@/lib/session-events", () => ({
  notifySessionsChanged: vi.fn(),
}));
vi.mock("@/components/space/SpaceSectionHeader", () => ({
  default: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
vi.mock("@/components/space/ArchivedConversations", () => ({
  default: ({ onRestore }: { onRestore: (id: string) => void }) => (
    <button onClick={() => onRestore("older")}>Unarchive</button>
  ),
}));
vi.mock("@/components/courses/OrganizedSessionList", () => ({
  default: ({
    sessions,
  }: {
    sessions: Array<{
      session_id: string;
      title: string;
      match_excerpt?: string;
    }>;
  }) => (
    <div>
      {sessions.map((session) => (
        <div key={session.session_id}>
          <span>{session.title}</span>
          {session.match_excerpt ? (
            <span>{session.match_excerpt}</span>
          ) : null}
        </div>
      ))}
    </div>
  ),
}));
vi.mock("@/lib/session-api", () => ({
  sessionWorkspaceId: (session?: { content_workspace_id?: string }) => session?.content_workspace_id ?? "",
  listAllSessions: vi.fn(async () => [
    {
      id: "recent",
      session_id: "recent",
      title: "Recent chat",
      created_at: 1,
      updated_at: 1,
      message_count: 2,
      last_message: "unrelated ending",
    },
  ]),
  searchAllSessions: vi.fn(
    async (query: string, signal?: AbortSignal) => {
      fixture.calls.push({ query, signal });
      return [
        {
          id: "older",
          session_id: "older",
          title: "Older conversation",
          created_at: 1,
          updated_at: 2,
          message_count: 4,
          last_message: "unrelated ending",
          match_excerpt: "Earlier transcript contains the term",
          match_role: "user",
          match_message_id: 7,
          match_created_at: 1,
        },
      ];
    },
  ),
  updateSessionTitle: vi.fn(),
  updateSessionOrganization: vi.fn(),
  deleteSession: vi.fn(),
}));

afterEach(() => {
  vi.useRealTimers();
  fixture.calls.length = 0;
  vi.clearAllMocks();
});

it("searches the full account history, then restores the unfiltered index", async () => {
  render(<ChatHistorySection />);

  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText("Recent chat")).toBeInTheDocument();

  vi.useFakeTimers();
  const input = screen.getByPlaceholderText("Search chat history...");
  fireEvent.change(input, { target: { value: "Bayes" } });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });

  expect(fixture.calls.map((call) => call.query)).toEqual(["Bayes"]);
  expect(screen.getByText("Earlier transcript contains the term")).toBeInTheDocument();
  expect(screen.getByText("Older conversation")).toBeInTheDocument();
  expect(screen.queryByText("Recent chat")).toBeNull();

  fireEvent.change(input, { target: { value: "" } });
  expect(screen.getByText("Recent chat")).toBeInTheDocument();
  expect(screen.queryByText("Older conversation")).toBeNull();
});

it("cancels a stale search when the query changes", async () => {
  render(<ChatHistorySection />);

  await act(async () => {
    await Promise.resolve();
  });

  vi.useFakeTimers();
  searchMock.mockImplementationOnce(
    (query: string, signal?: AbortSignal) => {
      fixture.calls.push({ query, signal });
      return new Promise((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    },
  );

  const input = screen.getByPlaceholderText("Search chat history...");
  await act(async () => {
    fireEvent.change(input, { target: { value: "Bay" } });
  });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });

  await act(async () => {
    fireEvent.change(input, { target: { value: "Bayes" } });
  });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });

  expect(fixture.calls.map((call) => call.query)).toEqual(["Bay", "Bayes"]);
  expect(fixture.calls[0].signal?.aborted).toBe(true);
  expect(fixture.calls[1].signal?.aborted).toBe(false);
  expect(screen.getByText("Older conversation")).toBeInTheDocument();
});

it("reports a failed transcript search and retries the same query", async () => {
  render(<ChatHistorySection />);
  await act(async () => { await Promise.resolve(); });
  vi.useFakeTimers();
  searchMock.mockRejectedValueOnce(new Error("Network unavailable"));
  fireEvent.change(screen.getByPlaceholderText("Search chat history..."), { target: { value: "Bayes" } });
  await act(async () => { vi.advanceTimersByTime(300); });
  expect(screen.getByRole("alert")).toHaveTextContent("Could not search chat history. Try again.");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await act(async () => { vi.advanceTimersByTime(300); });
  expect(searchMock).toHaveBeenLastCalledWith("Bayes", expect.any(AbortSignal), { allWorkspaces: true });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Older conversation")).toBeInTheDocument();
});

it("restores an archived search match in its own workspace", async () => {
  render(<ChatHistorySection />);
  await act(async () => { await Promise.resolve(); });
  vi.useFakeTimers();
  searchMock.mockResolvedValueOnce([{
    id: "older", session_id: "older", title: "Archived chat", created_at: 1, updated_at: 2,
    message_count: 4, last_message: "", content_workspace_id: "other-workspace",
    preferences: { archived: true }, match_excerpt: "Bayes", match_role: "user",
    match_message_id: 7, match_created_at: 1,
  }]);
  fireEvent.change(screen.getByLabelText("Filter by archive status"), { target: { value: "archived" } });
  fireEvent.change(screen.getByPlaceholderText("Search chat history..."), { target: { value: "Bayes" } });
  await act(async () => { vi.advanceTimersByTime(300); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unarchive" })); });
  expect(updateSessionOrganization).toHaveBeenCalledWith("older", { archived: false }, "other-workspace");
});
