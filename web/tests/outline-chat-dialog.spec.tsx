import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const resolveMasterySession = vi.fn(async () => ({
  session_id: "outline-1",
  created: false,
  mode: "outline",
  knowledge_point_id: "",
}));
const getSession = vi.fn(async () => ({
  id: "outline-1",
  session_id: "outline-1",
  title: "Outline",
  created_at: 0,
  updated_at: 1,
  status: "idle" as const,
  preferences: {},
  messages: [
    { id: 1, role: "user" as const, content: "Add a point about caching", events: [] },
    {
      id: 2,
      role: "assistant" as const,
      content: "Here is the revision.",
      events: [
        {
          type: "tool_call" as const,
          source: "chat",
          stage: "responding",
          content: "",
          timestamp: 0,
          metadata: { tool: "mastery_revise", call_id: "c1" },
        },
      ],
    },
  ],
  active_turns: [],
}));

vi.mock("@/lib/learning-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/learning-api")>()),
  resolveMasterySession: (...args: unknown[]) => resolveMasterySession(...(args as [])),
}));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: (...args: unknown[]) => getSession(...(args as [])),
}));
// The composer pulls KB + model lists on mount; the dialog test only needs to
// know it is mounted and wired.
vi.mock("@/components/chat/home/StandaloneComposer", () => ({
  default: () => <div data-testid="composer" />,
}));

import { OutlineChatDialog } from "@/components/space/learning/OutlineChatDialog";
import { initI18n } from "@/i18n/init";

initI18n("en");

afterEach(() => {
  resolveMasterySession.mockClear();
  getSession.mockClear();
});

describe("OutlineChatDialog", () => {
  it("loads the outline session into the shared chat surface", async () => {
    render(<OutlineChatDialog pathId="path-1" onClose={() => {}} />);

    // The dialog resolves + loads the outline conversation through the shared
    // adapter, so the transcript is the real ChatMessageList.
    await waitFor(() => expect(resolveMasterySession).toHaveBeenCalled());
    await waitFor(() => expect(getSession).toHaveBeenCalledWith("outline-1", undefined));
    await waitFor(() =>
      expect(screen.getByText("Here is the revision.")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("composer")).toBeInTheDocument();
    expect(screen.getByText("Outline chat")).toBeInTheDocument();
    // The whole point of reusing the shared surface: the tutor's tool work is
    // in the transcript (folded), instead of the old mini-chat's text-only view.
    expect(screen.getByText(/1 tool calls/)).toBeInTheDocument();
  });
});
