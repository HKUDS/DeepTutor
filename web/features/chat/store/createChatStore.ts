import { chatReducer, initialChatState } from "./reducer";
import type { ChatStoreAction, ChatStoreState } from "../model/types";

export interface ChatStore {
  getState(): ChatStoreState;
  dispatch(action: ChatStoreAction): void;
  subscribe(listener: () => void): () => void;
}

export function createChatStore(
  initialState: ChatStoreState = initialChatState,
): ChatStore {
  let state = initialState;
  const listeners = new Set<() => void>();
  return {
    getState: () => state,
    dispatch(action) {
      const next = chatReducer(state, action);
      if (next === state) return;
      state = next;
      for (const listener of listeners) listener();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
