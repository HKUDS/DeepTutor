"use client";

import {
  createContext,
  useContext,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { createChatStore, type ChatStore } from "./createChatStore";
import type { ChatStoreState } from "../model/types";

const ChatStoreContext = createContext<ChatStore | null>(null);

export function ChatStoreProvider({
  children,
  store,
}: {
  children: ReactNode;
  store?: ChatStore;
}) {
  const storeRef = useRef<ChatStore | null>(null);
  storeRef.current ??= store ?? createChatStore();
  return (
    <ChatStoreContext.Provider value={storeRef.current}>
      {children}
    </ChatStoreContext.Provider>
  );
}

export function useChatStore(): ChatStore {
  const store = useContext(ChatStoreContext);
  if (!store)
    throw new Error("useChatStore must be used inside ChatStoreProvider");
  return store;
}

export function useChatSelector<T>(selector: (state: ChatStoreState) => T): T {
  const store = useChatStore();
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getState()),
    () => selector(store.getState()),
  );
}
