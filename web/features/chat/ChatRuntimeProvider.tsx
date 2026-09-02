"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { StreamEvent } from "@/contracts/generated/turn-protocol";

import { ChatStateAdapterProvider } from "./ChatStateAdapter";

import { ChatActions } from "./store/ChatActions";
import { ChatStoreProvider } from "./store/ChatStoreProvider";
import { createChatStore, type ChatStore } from "./store/createChatStore";
import { TurnRuntimeClient } from "./transport/TurnRuntimeClient";

interface ChatRuntimeValue {
  actions: ChatActions;
  store: ChatStore;
}

const ChatRuntimeContext = createContext<ChatRuntimeValue | null>(null);

export function ChatRuntimeProvider({ children }: { children: ReactNode }) {
  const parent = useContext(ChatRuntimeContext);
  if (parent && process.env.NODE_ENV !== "production") {
    throw new Error(
      "ChatRuntimeProvider cannot be nested; scope one runtime per route subtree",
    );
  }

  const [value] = useState<ChatRuntimeValue>(() => {
    const store = createChatStore();
    const actions = new ChatActions(
      store,
      (sessionKey) =>
        new TurnRuntimeClient({
          onEvent(event) {
            if (event.type === "active_turn_info" || event.type === "pong")
              return;
            store.dispatch({
              type: "stream_event",
              key: sessionKey,
              event: event as StreamEvent,
            });
            if (event.type === "wait_for_input") {
              store.dispatch({
                type: "turn_status",
                key: sessionKey,
                status: "waiting_input",
                turnId: event.turn_id,
              });
            }
            if (event.type === "done") {
              const candidate = event.metadata?.status;
              const terminal =
                candidate === "failed" || candidate === "cancelled"
                  ? candidate
                  : "completed";
              store.dispatch({
                type: "turn_status",
                key: sessionKey,
                status: terminal,
              });
            }
          },
        }),
    );
    return { actions, store };
  });

  useEffect(() => () => value.actions.close(), [value]);

  return (
    <ChatRuntimeContext.Provider value={value}>
      <ChatStoreProvider store={value.store}>
        <ChatStateAdapterProvider>{children}</ChatStateAdapterProvider>
      </ChatStoreProvider>
    </ChatRuntimeContext.Provider>
  );
}

export function useChatActions(): ChatActions {
  const runtime = useContext(ChatRuntimeContext);
  if (!runtime)
    throw new Error("useChatActions must be used inside ChatRuntimeProvider");
  return runtime.actions;
}
