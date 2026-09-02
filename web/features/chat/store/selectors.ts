import type { ChatSession, ChatStoreState } from "../model/types";

export const selectActiveKey = (state: ChatStoreState): string | null =>
  state.activeKey;

export const selectActiveSession = (
  state: ChatStoreState,
): ChatSession | null =>
  state.activeKey ? (state.sessions[state.activeKey] ?? null) : null;

export const selectActiveMessages = (state: ChatStoreState) =>
  selectActiveSession(state)?.messages ?? EMPTY_MESSAGES;

export const selectSidebarSnapshot = (state: ChatStoreState) => state.sidebar;

export const selectSession = (key: string) => (state: ChatStoreState) =>
  state.sessions[key] ?? null;

const EMPTY_MESSAGES: ChatSession["messages"] = [];
