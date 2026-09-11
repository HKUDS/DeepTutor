import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import HistorySessionPicker from "@/components/chat/HistorySessionPicker";

const fixture = vi.hoisted(() => ({
  calls: [] as Array<{ query: string; signal?: AbortSignal }>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/PickerShell", () => ({
  default: ({
    open,
    children,
  }: {
    open: boolean;
    children: React.ReactNode;
  }) => (open ? <div>{children}</div> : null),
}));
vi.mock("@/components/common/PickerHeader", () => ({
  default: ({ title }: { title: string }) => <h2>{title}</h2>,
}));
vi.mock("@/lib/session-api", () => ({
  listSessions: vi.fn(async () => [
    {
      id: "recent",
      session_id: "recent",
      title: "Recent chat",
      created_at: 1,
      updated_at: 1,
      message_count: 1,
      last_message: "latest only",
    },
  ]),
  getSession: vi.fn(async (id: string) => ({
    id,
    session_id: id,
    title: id,
    created_at: 1,
    updated_at: 1,
    messages: [
      {
        id: 7,
        session_id: id,
        role: "user",
        content: `Matched body in ${id}`,
        events: [],
        attachments: [],
        created_at: 1,
      },
    ],
  })),
  searchSessions: vi.fn(
    async (
      query: string,
      _limit: number,
      _offset: number,
      signal?: AbortSignal,
    ) => {
      fixture.calls.push({ query, signal });
      return {
        sessions: [
          {
            id: `match-${query}`,
            session_id: `match-${query}`,
            title: "Older conversation",
            created_at: 1,
            updated_at: 1,
            message_count: 4,
            last_message: "unrelated ending",
            match_excerpt: `Earlier transcript contains ${query}`,
            match_role: "user",
            match_message_id: 7,
            match_created_at: 1,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      };
    },
  ),
}));

afterEach(() => {
  vi.useRealTimers();
  fixture.calls.length = 0;
});

it("debounces full-history search and aborts stale requests", async () => {
  vi.useFakeTimers();
  render(<HistorySessionPicker open onClose={vi.fn()} onApply={vi.fn()} />);
  await act(async () => undefined);
  expect(screen.getAllByText("Recent chat").length).toBeGreaterThan(0);

  const input = screen.getByPlaceholderText("Search full conversation history");
  fireEvent.change(input, { target: { value: "Bayes" } });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  expect(fixture.calls.map((call) => call.query)).toEqual(["Bayes"]);

  fireEvent.change(input, { target: { value: "posterior" } });
  expect(fixture.calls[0].signal?.aborted).toBe(true);
  await act(async () => {
    vi.advanceTimersByTime(300);
  });

  expect(fixture.calls.map((call) => call.query)).toEqual([
    "Bayes",
    "posterior",
  ]);
  expect(
    screen.getByText("Earlier transcript contains posterior"),
  ).toBeInTheDocument();
  await act(async () => {
    await Promise.resolve();
  });
  const focusedMessage = screen.getByText("Matched body in match-posterior");
  expect(focusedMessage.parentElement).toHaveClass("ring-1");
});
