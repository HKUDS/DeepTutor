import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";

import SessionViewerPanel, {
  type SessionViewerPanelHandle,
  type SessionViewerPanelProps,
} from "@/components/chat/home/SessionViewerPanel";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";
import { initI18n } from "@/i18n/init";
import { buildSessionActivity } from "@/lib/session-activity";

vi.mock("@/components/tasks/TaskPanelSection", () => ({ default: () => null }));
// Responder names come from the shared rosters; these tests name them directly.
vi.mock("@/hooks/usePartnerRoster", () => ({
  usePartnerRoster: () => ({
    partners: [{ partner_id: "ada", name: "Ada" }],
    loading: false,
    error: false,
  }),
}));
vi.mock("@/hooks/usePartnerGroups", () => ({
  usePartnerGroups: () => ({ groups: [], loading: false, error: false }),
}));
// The composer is the main chat's; what this suite checks is the tab around it.
vi.mock("@/components/quiz/FollowupChatComposer", () => ({ default: () => null }));

const api = vi.hoisted(() => ({
  listSessionThreads: vi.fn(async () => [] as unknown[]),
  getSession: vi.fn(async () => ({ messages: [] as unknown[] })),
}));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  listSessionThreads: api.listSessionThreads,
  getSession: api.getSession,
}));

initI18n("en");

afterEach(() => {
  cleanup();
  api.listSessionThreads.mockReset().mockResolvedValue([]);
  api.getSession.mockReset().mockResolvedValue({ messages: [] });
});

const conversation = { title: "Fork and exec", leafMessageId: 12, language: "en" };

function renderPanel(props: Partial<SessionViewerPanelProps> = {}) {
  const ref = createRef<SessionViewerPanelHandle>();
  const base: SessionViewerPanelProps = {
    open: true,
    sessionId: "session-a",
    sessionKey: "session-a",
    activity: buildSessionActivity([]),
    onClose: () => {},
    onAutoOpen: () => {},
    ...props,
  };
  const view = render(
    <QuizFollowupProvider>
      <SessionViewerPanel ref={ref} {...base} />
    </QuizFollowupProvider>,
  );
  const rerender = (next: Partial<SessionViewerPanelProps>) =>
    view.rerender(
      <QuizFollowupProvider>
        <SessionViewerPanel ref={ref} {...base} {...next} />
      </QuizFollowupProvider>,
    );
  return { ref, rerender };
}

/** The panel slides in over two frames and is aria-hidden until it has. */
const entered = () => screen.findByRole("button", { name: "New tab" });

const tabBar = () => screen.getByRole("button", { name: "New tab" }).parentElement!.parentElement!;

it("names every tool on the launcher, and opening things lives there alone", async () => {
  renderPanel({ conversation: null });
  await entered();

  // The Activity home is a record of the conversation, not a second opener.
  expect(await screen.findByRole("button", { name: "Back to conversation" })).toBeVisible();
  expect(screen.queryByText("Open a local file")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "New tab" }));

  expect(await screen.findByRole("textbox", { name: "Open URL" })).toBeVisible();
  for (const name of ["Note", "Open a local file", "GeoGebra board"]) {
    expect(screen.getByRole("button", { name: new RegExp(name) })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  }
  // Nothing to talk about yet, and the side chat still opens: beside a draft
  // it is a conversation of its own. Who answers is one click away.
  expect(screen.getByRole("button", { name: /Ask Dito/ })).not.toHaveAttribute(
    "aria-disabled",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Ask someone else" }));
  expect(screen.getByRole("menuitem", { name: /Ada/ })).toBeVisible();
  fireEvent.click(screen.getByRole("menuitem", { name: /Ada/ }));
  expect(await within(tabBar()).findByRole("button", { name: "Ada" })).toBeVisible();
  expect(screen.getByText(/Ada answers here/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  expect(screen.getByText(/open here on their own/)).toBeVisible();
});

it("opens a side chat on the conversation it was started from", async () => {
  renderPanel({ conversation });
  await entered();

  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  fireEvent.click(await screen.findByRole("button", { name: /Ask Dito/ }));

  expect(await screen.findByText("About this conversation")).toBeVisible();
  expect(screen.getByText("Fork and exec")).toBeVisible();
  expect(within(tabBar()).getByRole("button", { name: "Dito" })).toBeVisible();
  // The launcher gave way to what it opened: only the "+" is left by that name.
  expect(within(tabBar()).getAllByRole("button", { name: "New tab" })).toHaveLength(1);

  // A second ask focuses the blank side chat instead of stacking another.
  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  fireEvent.click(await screen.findByRole("button", { name: /Ask Dito/ }));
  expect(within(tabBar()).getAllByRole("button", { name: "Dito" })).toHaveLength(1);
});

it("asks about a passage in the side chat already talking to that responder", async () => {
  const { ref } = renderPanel({ conversation });
  await entered();
  const ada = { kind: "partner" as const, id: "ada", name: "Ada" };

  act(() => ref.current!.openSideChatTab({ responder: ada, quote: "rc = fork()" }));
  expect(await within(tabBar()).findByRole("button", { name: "Ada" })).toBeVisible();
  expect(screen.getByText(/Ada answers here/)).toBeVisible();

  // Another passage for Ada joins the thread already open with Ada; Dito gets one of its own.
  act(() => ref.current!.openSideChatTab({ responder: ada, quote: "execve()" }));
  expect(within(tabBar()).getAllByRole("button", { name: "Ada" })).toHaveLength(1);
  act(() => ref.current!.openSideChatTab({ quote: "execve()" }));
  expect(await within(tabBar()).findByRole("button", { name: "Dito" })).toBeVisible();
});

it("keeps tabs with their conversation, and with a draft that becomes one", async () => {
  const { ref, rerender } = renderPanel({ sessionId: null, sessionKey: "draft-1" });
  await entered();

  act(() => ref.current!.openWebTab("https://example.com/notes"));
  expect(await within(tabBar()).findByRole("button", { name: "example.com" })).toBeVisible();

  // The first turn binds the draft: same conversation, new key.
  rerender({ sessionId: "session-a", sessionKey: "session-a", reboundFromKey: "draft-1" });
  expect(within(tabBar()).getByRole("button", { name: "example.com" })).toBeVisible();

  // Leaving stashes the tabs; coming back restores them.
  rerender({ sessionId: "session-b", sessionKey: "session-b", reboundFromKey: null });
  expect(within(tabBar()).queryByRole("button", { name: "example.com" })).toBeNull();
  rerender({ sessionId: "session-a", sessionKey: "session-a", reboundFromKey: "draft-1" });
  expect(within(tabBar()).getByRole("button", { name: "example.com" })).toBeVisible();
});

it("offers a closed tab back from the launcher", async () => {
  const { ref } = renderPanel();
  await entered();

  act(() => ref.current!.openWebTab("https://example.com/notes"));
  fireEvent.click(await within(tabBar()).findByRole("button", { name: "Close tab" }));
  expect(within(tabBar()).queryByRole("button", { name: "example.com" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  const row = await screen.findByRole("button", { name: /example\.com.*Recently closed/ });
  fireEvent.click(row);

  expect(within(tabBar()).getByRole("button", { name: "example.com" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  expect(screen.queryByText("Recently closed")).toBeNull();
});

it("brings an earlier side chat back with its history and who answered it", async () => {
  api.listSessionThreads.mockResolvedValue([
    {
      id: "thread-1",
      session_id: "thread-1",
      title: "Why fork returns twice",
      created_at: 1,
      updated_at: 1_700_000_000,
      message_count: 2,
      last_message: "",
      preferences: {
        parent_session_id: "session-a",
        session_kind: "selection_tutor",
        answer_by: "partner:ada",
      },
    },
  ]);
  api.getSession.mockResolvedValue({
    messages: [
      {
        role: "user",
        content: "Why twice?",
        events: [],
        attachments: [{ type: "quote", filename: "quote.md", extracted_text: "rc = fork()" }],
      },
      { role: "assistant", content: "Once in each process.", events: [] },
    ],
  });
  renderPanel({ conversation, workspaceId: "algebra" });
  await entered();

  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  const row = await screen.findByRole("button", { name: /Why fork returns twice/ });
  expect(api.listSessionThreads).toHaveBeenCalledWith("session-a", "algebra", expect.anything());
  expect(row).toHaveTextContent("With Ada");
  fireEvent.click(row);

  expect(await within(tabBar()).findByRole("button", { name: "Ada" })).toBeVisible();
  await waitFor(() => expect(screen.getByText("Once in each process.")).toBeVisible());
  expect(screen.getByText("rc = fork()")).toBeVisible();
  expect(api.getSession).toHaveBeenCalledWith("thread-1");

  // An open thread is not offered again.
  fireEvent.click(screen.getByRole("button", { name: "New tab" }));
  await waitFor(() => expect(api.listSessionThreads).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("button", { name: /Why fork returns twice/ })).toBeNull();
});
