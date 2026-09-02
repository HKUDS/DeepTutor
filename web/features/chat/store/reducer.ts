import type { StreamEvent } from "@/contracts/generated/turn-protocol";

import type {
  ChatSession,
  ChatStoreAction,
  ChatStoreState,
  SidebarSessionSummary,
} from "../model/types";

export const MAX_CACHED_CHAT_SESSIONS = 20;

export const initialChatState: ChatStoreState = {
  activeKey: null,
  sessions: {},
  sidebar: { revision: 0, sessions: [] },
};

export function createChatSession(key: string, now = Date.now()): ChatSession {
  return {
    key,
    id: null,
    title: "",
    messages: [],
    status: "idle",
    queryState: "idle",
    activeTurnId: null,
    lastSeq: 0,
    cancellationRequested: false,
    selectedBranches: {},
    updatedAt: now,
  };
}

function summary(session: ChatSession): SidebarSessionSummary {
  return {
    key: session.key,
    id: session.id,
    title: session.title,
    status: session.status,
    updatedAt: session.updatedAt,
  };
}

function updateSidebar(
  state: ChatStoreState,
  session: ChatSession,
): ChatStoreState["sidebar"] {
  const sessions = [
    summary(session),
    ...state.sidebar.sessions.filter((item) => item.key !== session.key),
  ].sort((left, right) => right.updatedAt - left.updatedAt);
  return { revision: state.sidebar.revision + 1, sessions };
}

function withSession(
  state: ChatStoreState,
  key: string,
  update: (session: ChatSession) => ChatSession,
  sidebar = false,
): ChatStoreState {
  const current = state.sessions[key];
  if (!current) return state;
  const next = update(current);
  return {
    ...state,
    sessions: { ...state.sessions, [key]: next },
    sidebar: sidebar ? updateSidebar(state, next) : state.sidebar,
  };
}

function appendEvent(session: ChatSession, event: StreamEvent): ChatSession {
  const seq = event.seq ?? 0;
  if (seq <= session.lastSeq) return session;
  const messages = [...session.messages];
  const index = messages.length - 1;
  const current = messages[index];
  if (!current || current.role !== "assistant") return session;
  messages[index] = {
    ...current,
    content:
      event.type === "content"
        ? current.content + (event.content ?? "")
        : current.content,
    events: [...(current.events ?? []), event],
  };
  return {
    ...session,
    messages,
    activeTurnId: event.turn_id || session.activeTurnId,
    lastSeq: seq,
    updatedAt: Date.now(),
  };
}

function evictSessions(state: ChatStoreState): ChatStoreState {
  const entries = Object.values(state.sessions);
  if (entries.length <= MAX_CACHED_CHAT_SESSIONS) return state;
  const removable = entries
    .filter(
      (session) =>
        session.key !== state.activeKey && session.status !== "running",
    )
    .sort((left, right) => left.updatedAt - right.updatedAt);
  const sessions = { ...state.sessions };
  for (const session of removable.slice(
    0,
    entries.length - MAX_CACHED_CHAT_SESSIONS,
  )) {
    delete sessions[session.key];
  }
  return { ...state, sessions };
}

export function chatReducer(
  state: ChatStoreState,
  action: ChatStoreAction,
): ChatStoreState {
  switch (action.type) {
    case "ensure_session": {
      if (state.sessions[action.key]) return state;
      const session = createChatSession(action.key);
      return evictSessions({
        ...state,
        activeKey: state.activeKey ?? action.key,
        sessions: { ...state.sessions, [action.key]: session },
        sidebar: updateSidebar(state, session),
      });
    }
    case "select_session":
      return state.sessions[action.key] && state.activeKey !== action.key
        ? { ...state, activeKey: action.key }
        : state;
    case "remove_session": {
      if (!state.sessions[action.key]) return state;
      const sessions = { ...state.sessions };
      delete sessions[action.key];
      return {
        ...state,
        activeKey: state.activeKey === action.key ? null : state.activeKey,
        sessions,
        sidebar: {
          revision: state.sidebar.revision + 1,
          sessions: state.sidebar.sessions.filter(
            (item) => item.key !== action.key,
          ),
        },
      };
    }
    case "load_session": {
      const next = {
        ...state,
        activeKey: action.session.key,
        sessions: { ...state.sessions, [action.session.key]: action.session },
        sidebar: updateSidebar(state, action.session),
      };
      return evictSessions(next);
    }
    case "add_optimistic_turn":
      return withSession(state, action.key, (session) => ({
        ...session,
        messages: [...session.messages, action.user, action.assistant],
        status: "running",
        queryState: "running",
        cancellationRequested: false,
        updatedAt: Date.now(),
      }));
    case "stream_event":
      return withSession(state, action.key, (session) =>
        appendEvent(session, action.event),
      );
    case "turn_status":
      return withSession(
        state,
        action.key,
        (session) => ({
          ...session,
          status: action.status,
          queryState: action.queryState ?? action.status,
          activeTurnId:
            action.status === "completed" ||
            action.status === "cancelled" ||
            action.status === "failed"
              ? null
              : (action.turnId ?? session.activeTurnId),
          cancellationRequested: false,
          updatedAt: Date.now(),
        }),
        true,
      );
    case "cancel_requested":
      return withSession(state, action.key, (session) => ({
        ...session,
        cancellationRequested: true,
      }));
    case "session_meta":
      return withSession(
        state,
        action.key,
        (session) => ({
          ...session,
          title: action.title,
          updatedAt: Date.now(),
        }),
        true,
      );
    case "set_branch":
      return withSession(state, action.key, (session) => ({
        ...session,
        selectedBranches: {
          ...session.selectedBranches,
          [action.parentKey]: action.childId,
        },
      }));
    case "delete_messages": {
      const ids = new Set(action.ids);
      return withSession(
        state,
        action.key,
        (session) => ({
          ...session,
          messages: session.messages.filter((message) => !ids.has(message.id)),
          updatedAt: Date.now(),
        }),
        true,
      );
    }
    case "regenerate_rollback":
      return withSession(state, action.key, (session) => ({
        ...session,
        messages: [
          ...session.messages.filter((message) => message.content),
          action.assistant,
        ],
        status: "idle",
        queryState: "idle",
      }));
    default:
      return state;
  }
}
