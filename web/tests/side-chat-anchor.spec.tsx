import { act, cleanup, render, screen } from "@testing-library/react";
import { createRef, useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";

import SessionViewerPanel, {
  type SessionViewerPanelHandle,
  type SessionViewerPanelProps,
} from "@/components/chat/home/SessionViewerPanel";
import {
  QuizFollowupProvider,
  useQuizFollowupController,
  type QuizFollowupController,
  type QuizFollowupTabContext,
} from "@/context/QuizFollowupContext";
import { initI18n } from "@/i18n/init";
import { buildSessionActivity } from "@/lib/session-activity";
import type { SessionSummary } from "@/lib/session-api";

vi.mock("@/components/tasks/TaskPanelSection", () => ({ default: () => null }));
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

// The composer is where the next send's quoted_message_id is decided; the
// probe shows the anchor the tab would submit, without mounting the composer.
vi.mock("@/components/quiz/FollowupChatComposer", () => ({
  default: ({ context }: { context: QuizFollowupTabContext }) => (
    <div data-testid="side-chat-anchor" data-question-key={context.questionKey}>
      {String(context.sideChat?.sourceMessageId ?? "none")}
    </div>
  ),
}));

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
const ada = { kind: "partner" as const, id: "ada", name: "Ada" };

function renderPanel(onController?: (controller: QuizFollowupController) => void) {
  const ref = createRef<SessionViewerPanelHandle>();
  const props: SessionViewerPanelProps = {
    open: true,
    sessionId: "session-a",
    sessionKey: "session-a",
    conversation,
    activity: buildSessionActivity([]),
    onClose: () => {},
    onAutoOpen: () => {},
  };
  render(
    <QuizFollowupProvider>
      <SessionViewerPanel ref={ref} {...props} />
      {onController ? <ControllerProbe onReady={onController} /> : null}
    </QuizFollowupProvider>,
  );
  return ref;
}

/** Reaches the live thread state a side chat's first send writes into. */
function ControllerProbe({
  onReady,
}: {
  onReady: (controller: QuizFollowupController) => void;
}) {
  const controller = useQuizFollowupController();
  useEffect(() => onReady(controller), [controller, onReady]);
  return null;
}

function threadRow(sourceMessageId: number | string | null): SessionSummary {
  return {
    id: "thread-1",
    session_id: "thread-1",
    title: "Why fork returns twice",
    created_at: 1,
    updated_at: 1_700_000_000,
    message_count: 0,
    last_message: "",
    preferences: {
      parent_session_id: "session-a",
      session_kind: "selection_tutor",
      answer_by: "partner:ada",
      tutor_source_message_id: sourceMessageId,
    },
  };
}

const anchor = () => screen.getByTestId("side-chat-anchor");

it("moves the anchor with a new selection but keeps it when opened bare", async () => {
  const ref = renderPanel();

  act(() =>
    ref.current!.openSideChatTab({
      responder: ada,
      quote: "rc = fork()",
      sourceMessageId: 7,
    }),
  );
  expect(await screen.findByTestId("side-chat-anchor")).toHaveTextContent("7");

  // Bare open: nothing new is being asked about, so the thread stays put.
  act(() => ref.current!.openSideChatTab({ responder: ada }));
  expect(anchor()).toHaveTextContent("7");
});

it("leaves the thread unattached when a new selection has no persisted message", async () => {
  const ref = renderPanel();

  act(() =>
    ref.current!.openSideChatTab({
      responder: ada,
      quote: "rc = fork()",
      sourceMessageId: 7,
    }),
  );
  expect(await screen.findByTestId("side-chat-anchor")).toHaveTextContent("7");

  // The passage comes from an optimistic row: its negative temporary id is
  // not a message the thread can be filed under, so the old anchor must go.
  act(() =>
    ref.current!.openSideChatTab({
      responder: ada,
      quote: "A draft passage",
      sourceMessageId: null,
    }),
  );
  expect(anchor()).toHaveTextContent("none");
});

it("forgets an open tab's anchor when its thread is detached", async () => {
  const ref = renderPanel();

  act(() => ref.current!.openSideChatThread(threadRow(7)));
  expect(await screen.findByTestId("side-chat-anchor")).toHaveTextContent("7");

  act(() => ref.current!.clearSideChatSource("thread-1", 7));
  expect(anchor()).toHaveTextContent("none");
});

it("forgets a new side chat's anchor once its first send binds a session", async () => {
  let controller: QuizFollowupController | null = null;
  const ref = renderPanel((ready) => {
    controller = ready;
  });

  act(() =>
    ref.current!.openSideChatTab({
      responder: ada,
      quote: "rc = fork()",
      sourceMessageId: 7,
    }),
  );
  expect(await screen.findByTestId("side-chat-anchor")).toHaveTextContent("7");

  // A brand-new side chat has sent its first turn: the message-level entry
  // exists, but the tab still has no followupSessionId — the bound session
  // only lives in the thread state the send wrote.
  const key = anchor().getAttribute("data-question-key")!;
  act(() =>
    controller!.updateThread(key, (prev) => ({ ...prev, sessionId: "thread-1" })),
  );

  act(() => ref.current!.clearSideChatSource("thread-1", 7));
  expect(anchor()).toHaveTextContent("none");
});

it("keeps an anchor the learner moved after the detached one", async () => {
  const ref = renderPanel();

  act(() => ref.current!.openSideChatThread(threadRow(7)));
  expect(await screen.findByTestId("side-chat-anchor")).toHaveTextContent("7");

  act(() =>
    ref.current!.openSideChatTab({
      responder: ada,
      quote: "execve()",
      sourceMessageId: 9,
    }),
  );
  expect(anchor()).toHaveTextContent("9");

  // The marker under message 7 was detached, but the tab already points at 9:
  // the newest selection wins over the entry point that was removed.
  act(() => ref.current!.clearSideChatSource("thread-1", 7));
  expect(anchor()).toHaveTextContent("9");
});
