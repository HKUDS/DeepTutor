import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PartnerChat from "@/components/partners/PartnerChat";

interface MockComposerProps {
  onSend: (content: string, attachments: []) => boolean | "handled";
  restoreDraft?: { id: number; content: string; attachments: unknown[] };
  disabled?: boolean;
}

const api = vi.hoisted(() => ({
  historyPage: vi.fn(),
  sessions: vi.fn(),
  commands: vi.fn(),
}));
const translate = vi.hoisted(() => (key: string) => key);
const composer = vi.hoisted(() => ({ current: null as MockComposerProps | null }));
const sockets = vi.hoisted(() => ({
  instances: [] as Array<{
    emit: (frame: Record<string, unknown>) => void;
    messages: string[];
  }>,
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@/lib/partners-api", () => ({
  getPartnerHistoryPage: api.historyPage,
  getPartnerSessions: api.sessions,
  getPartnerCommands: api.commands,
}));
vi.mock("@/lib/reconnecting-websocket", () => {
  class MockSocket {
    connected = true;
    messages: string[] = [];
    constructor(
      _url: string,
      private handlers: {
        onOpen: () => void;
        onMessage: (event: MessageEvent) => void;
        onDisconnect: () => void;
      },
    ) {
      sockets.instances.push(this);
    }
    start() {
      this.handlers.onOpen();
      this.emit({ type: "ready" });
    }
    send(payload: string) {
      this.messages.push(payload);
      return true;
    }
    stop() {}
    wake() {}
    emit(frame: Record<string, unknown>) {
      this.handlers.onMessage({ data: JSON.stringify(frame) } as MessageEvent);
    }
    disconnect() {
      this.handlers.onDisconnect();
    }
  }
  return { ReconnectingWebSocket: MockSocket };
});
vi.mock("@/components/partners/PartnerComposer", () => ({
  PartnerComposer: (props: MockComposerProps) => {
    composer.current = props;
    return <div data-testid="composer" />;
  },
}));
vi.mock("@/components/partners/PartnerAvatar", () => ({
  default: () => <div data-testid="avatar" />,
}));
vi.mock("@/features/chat/trace", () => ({ AssistantActivity: () => null }));
vi.mock("next/dynamic", () => ({
  default: () => ({ content }: { content: string }) => <span>{content}</span>,
}));
vi.mock("@/hooks/useChatAutoScroll", async () => {
  const React = await import("react");
  return {
    useChatAutoScroll: () => ({
      containerRef: React.useRef<HTMLDivElement>(null),
      shouldAutoScrollRef: React.useRef(true),
      scrollToBottom: React.useCallback(() => {}, []),
      handleScroll: React.useCallback(() => {}, []),
    }),
  };
});

const initialPage = {
  messages: [{ role: "assistant", content: "Earlier answer" }],
  start: 0,
  total: 1,
  next_before: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  sockets.instances.length = 0;
  composer.current = null;
  api.historyPage.mockResolvedValue(initialPage);
  api.sessions.mockResolvedValue([]);
  api.commands.mockResolvedValue([]);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

async function ready() {
  await waitFor(() => expect(composer.current?.disabled).toBe(false));
  return sockets.instances[0];
}

it.each(["turn_busy", "stale_session"])(
  "restores the rejected draft after %s and removes its optimistic row",
  async (type) => {
    const onSelectionStale = vi.fn();
    render(
      <PartnerChat
        partnerId="ada"
        partnerName="Ada"
        sessionKey="web-current"
        onSelectionStale={onSelectionStale}
      />,
    );
    const socket = await ready();
    act(() => {
      expect(composer.current?.onSend("Keep this draft", [])).toBe(true);
    });
    expect(screen.getByText("Keep this draft")).toBeInTheDocument();
    act(() => socket.emit({ type }));
    await waitFor(() => {
      expect(composer.current?.restoreDraft?.content).toBe("Keep this draft");
      expect(screen.queryByText("Keep this draft")).not.toBeInTheDocument();
    });
    expect(onSelectionStale).toHaveBeenCalledTimes(type === "stale_session" ? 1 : 0);
  },
);

it("keeps an accepted question when the turn later errors", async () => {
  render(<PartnerChat partnerId="ada" partnerName="Ada" sessionKey="web-current" />);
  const socket = await ready();
  act(() => {
    expect(composer.current?.onSend("Submitted question", [])).toBe(true);
    socket.emit({ type: "accepted", session_key: "web-current" });
    socket.emit({ type: "error", content: "Provider unavailable" });
    socket.emit({ type: "done" });
  });
  expect(screen.getByText("Submitted question")).toBeInTheDocument();
  expect(screen.getByText("Provider unavailable")).toBeInTheDocument();
  expect(composer.current?.restoreDraft).toBeUndefined();
});

it("restores a question rejected before acceptance", async () => {
  render(<PartnerChat partnerId="ada" partnerName="Ada" sessionKey="web-current" />);
  const socket = await ready();
  act(() => {
    expect(composer.current?.onSend("Invalid attachment question", [])).toBe(true);
    socket.emit({ type: "error", content: "Invalid attachments" });
  });
  expect(screen.queryByText("Invalid attachment question")).not.toBeInTheDocument();
  expect(composer.current?.restoreDraft?.content).toBe("Invalid attachment question");
});

it("clears the pending send when a turn stops so shared history can refresh", async () => {
  api.historyPage
    .mockResolvedValueOnce(initialPage)
    .mockResolvedValueOnce({
      messages: [
        { role: "assistant", content: "Earlier answer" },
        { role: "assistant", content: "Other browser answer" },
      ],
      start: 0,
      total: 2,
      next_before: null,
    });
  render(
    <PartnerChat partnerId="ada" partnerName="Ada" sessionKey="web-current" sharedAcrossBrowsers />,
  );
  const socket = await ready();
  act(() => {
    expect(composer.current?.onSend("Cancelled question", [])).toBe(true);
    socket.emit({ type: "accepted", session_key: "web-current" });
    socket.emit({ type: "stopped" });
  });
  act(() => window.dispatchEvent(new Event("focus")));
  expect(await screen.findByText("Other browser answer")).toBeInTheDocument();
});

it("keeps an optimistic send while an earlier history poll resolves", async () => {
  let resolveRefresh: ((value: typeof initialPage) => void) | undefined;
  api.historyPage
    .mockResolvedValueOnce(initialPage)
    .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
  render(
    <PartnerChat
      partnerId="ada"
      partnerName="Ada"
      sessionKey="web-current"
      sharedAcrossBrowsers
    />,
  );
  await ready();
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(api.historyPage).toHaveBeenCalledTimes(2));
  act(() => {
    expect(composer.current?.onSend("Optimistic question", [])).toBe(true);
  });
  await act(async () => {
    resolveRefresh?.({
      messages: [
        { role: "assistant", content: "Earlier answer" },
        { role: "assistant", content: "Other browser answer" },
      ],
      start: 0,
      total: 2,
      next_before: null,
    });
  });
  expect(screen.getByText("Optimistic question")).toBeInTheDocument();
  expect(screen.queryByText("Other browser answer")).not.toBeInTheDocument();
});

it("does not recreate the socket for an ordinary parent rerender", async () => {
  const onSelectionStale = vi.fn();
  const { rerender } = render(
    <PartnerChat
      partnerId="ada"
      partnerName="Ada"
      sessionKey="web-current"
      onSelectionStale={onSelectionStale}
    />,
  );
  await ready();
  rerender(
    <PartnerChat
      partnerId="ada"
      partnerName="Ada renamed"
      sessionKey="web-current"
      onSelectionStale={onSelectionStale}
    />,
  );
  expect(sockets.instances).toHaveLength(1);
});
