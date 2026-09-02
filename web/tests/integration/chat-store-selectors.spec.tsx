import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ChatStoreProvider,
  useChatSelector,
} from "@/features/chat/store/ChatStoreProvider";
import { createChatStore } from "@/features/chat/store/createChatStore";
import {
  selectActiveMessages,
  selectSidebarSnapshot,
} from "@/features/chat/store/selectors";

function MessageConsumer({ onRender }: { onRender: () => void }) {
  const messages = useChatSelector(selectActiveMessages);
  useEffect(onRender);
  return <output data-testid="messages">{messages.at(-1)?.content}</output>;
}

function SidebarConsumer({ onRender }: { onRender: () => void }) {
  const sidebar = useChatSelector(selectSidebarSnapshot);
  useEffect(onRender);
  return <output data-testid="sidebar">{sidebar.sessions.length}</output>;
}

describe("chat selector isolation", () => {
  it("does not rerender sidebar consumers during a 500-token stream", () => {
    const onMessageRender = vi.fn();
    const onSidebarRender = vi.fn();
    const store = createChatStore();
    store.dispatch({ type: "ensure_session", key: "draft" });
    store.dispatch({
      type: "add_optimistic_turn",
      key: "draft",
      user: { id: -2, role: "user", content: "q", parentMessageId: null },
      assistant: {
        id: -1,
        role: "assistant",
        content: "",
        parentMessageId: -2,
      },
    });
    render(
      <ChatStoreProvider store={store}>
        <MessageConsumer onRender={onMessageRender} />
        <SidebarConsumer onRender={onSidebarRender} />
      </ChatStoreProvider>,
    );

    const sidebarBefore = screen.getByTestId("sidebar").textContent;
    for (let seq = 1; seq <= 500; seq += 1) {
      act(() => {
        store.dispatch({
          type: "stream_event",
          key: "draft",
          event: {
            type: "content",
            turn_id: "turn-1",
            seq,
            timestamp: seq,
            content: "x",
            metadata: {},
          },
        });
      });
    }

    expect(screen.getByTestId("messages").textContent).toHaveLength(500);
    expect(screen.getByTestId("sidebar").textContent).toBe(sidebarBefore);
    expect(onMessageRender).toHaveBeenCalledTimes(501);
    expect(onSidebarRender).toHaveBeenCalledTimes(1);
  });
});
