"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import {
  readStoredLanguage,
  writeStoredActiveSessionId,
} from "@/context/AppShellContext";
import type { StreamEvent, ChatMessage } from "@/lib/unified-ws";
import { UnifiedWSClient } from "@/lib/unified-ws";
import { getSession, type SessionMessage } from "@/lib/session-api";
import { normalizeMarkdownForDisplay } from "@/lib/markdown-display";
import { shouldAppendEventContent } from "@/lib/stream";

type SessionRuntimeStatus =
  | "idle"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "rejected";

interface OutgoingAttachment {
  type: string;
  url?: string;
  base64?: string;
  filename?: string;
  mime_type?: string;
}

interface NotebookReferencePayload {
  notebook_id: string;
  record_ids: string[];
}

type HistoryReferencePayload = string[];

export interface SendMessageOptions {
  displayUserMessage?: boolean;
  persistUserMessage?: boolean;
  requestSnapshotOverride?: MessageRequestSnapshot;
}

export interface ChatState {
  sessionId: string | null;
  enabledTools: string[];
  activeCapability: string | null;
  knowledgeBases: string[];
  messages: MessageItem[];
  isStreaming: boolean;
  currentStage: string;
  language: string;
}

interface SessionStatusSnapshot {
  sessionId: string;
  status: SessionRuntimeStatus;
  activeTurnId: string | null;
  updatedAt: number;
}

export interface MessageAttachment {
  type: string;
  filename?: string;
  base64?: string;
  url?: string;
  mime_type?: string;
}

export interface MessageRequestSnapshot {
  content: string;
  capability?: string | null;
  enabledTools: string[];
  knowledgeBases: string[];
  language: string;
  attachments?: MessageAttachment[];
  config?: Record<string, unknown>;
  notebookReferences?: NotebookReferencePayload[];
  historyReferences?: HistoryReferencePayload;
}

export interface MessageItem {
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
  events?: StreamEvent[];
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
}

interface SessionEntry extends ChatState {
  key: string;
  status: SessionRuntimeStatus;
  activeTurnId: string | null;
  lastSeq: number;
  updatedAt: number;
}

interface ProviderState {
  selectedKey: string | null;
  sessions: Record<string, SessionEntry>;
  sidebarRefreshToken: number;
}

type Action =
  | { type: "SET_TOOLS"; tools: string[] }
  | { type: "SET_CAPABILITY"; cap: string | null }
  | { type: "SET_KB"; kbs: string[] }
  | { type: "SET_LANGUAGE"; lang: string }
  | {
      type: "ADD_USER_MSG";
      key: string;
      content: string;
      capability?: string | null;
      attachments?: MessageAttachment[];
      requestSnapshot?: MessageRequestSnapshot;
    }
  | { type: "STREAM_START"; key: string }
  | { type: "STREAM_EVENT"; key: string; event: StreamEvent }
  | { type: "STREAM_END"; key: string; status?: SessionRuntimeStatus; turnId?: string | null }
  | { type: "BIND_SERVER_SESSION"; key: string; sessionId: string; turnId?: string | null }
  | {
      type: "LOAD_SESSION";
      key: string;
      sessionId: string;
      messages: MessageItem[];
      activeTurnId?: string | null;
      status?: SessionRuntimeStatus;
      tools?: string[];
      capability?: string | null;
      knowledgeBases?: string[];
      language?: string;
    }
  | { type: "NEW_SESSION"; key: string };

function createSessionEntry(key: string, sessionId: string | null = null): SessionEntry {
  return {
    key,
    sessionId,
    enabledTools: [],
    activeCapability: null,
    knowledgeBases: [],
    messages: [],
    isStreaming: false,
    currentStage: "",
    language: typeof window === "undefined" ? "en" : readStoredLanguage(),
    status: "idle",
    activeTurnId: null,
    lastSeq: 0,
    updatedAt: Date.now(),
  };
}

function ensureSelectedSession(state: ProviderState): SessionEntry {
  if (state.selectedKey && state.sessions[state.selectedKey]) {
    return state.sessions[state.selectedKey];
  }
  return createSessionEntry("draft");
}

function updateSelectedSession(
  state: ProviderState,
  updater: (session: SessionEntry) => SessionEntry,
): ProviderState {
  const current = ensureSelectedSession(state);
  const key = state.selectedKey || current.key;
  const nextSession = updater(current);
  return {
    ...state,
    selectedKey: key,
    sessions: {
      ...state.sessions,
      [key]: nextSession,
    },
  };
}

function reducer(state: ProviderState, action: Action): ProviderState {
  switch (action.type) {
    case "SET_TOOLS":
      return updateSelectedSession(state, (session) => ({
        ...session,
        enabledTools: action.tools,
      }));
    case "SET_CAPABILITY":
      return updateSelectedSession(state, (session) => ({
        ...session,
        activeCapability: action.cap,
      }));
    case "SET_KB":
      return updateSelectedSession(state, (session) => ({
        ...session,
        knowledgeBases: action.kbs,
      }));
    case "SET_LANGUAGE":
      return updateSelectedSession(state, (session) => ({
        ...session,
        language: action.lang,
      }));
    case "ADD_USER_MSG": {
      const session = state.sessions[action.key] ?? createSessionEntry(action.key);
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: [
              ...session.messages,
              {
                role: "user",
                content: action.content,
                capability: action.capability || "",
                ...(action.attachments?.length ? { attachments: action.attachments } : {}),
                ...(action.requestSnapshot ? { requestSnapshot: action.requestSnapshot } : {}),
              },
            ],
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "STREAM_START":
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...(state.sessions[action.key] ?? createSessionEntry(action.key)),
            isStreaming: true,
            status: "running",
            messages: [
              ...(state.sessions[action.key]?.messages ?? []),
              {
                role: "assistant",
                content: "",
                events: [],
                capability: (state.sessions[action.key] ?? createSessionEntry(action.key)).activeCapability || "",
              },
            ],
            updatedAt: Date.now(),
          },
        },
      };
    case "STREAM_EVENT": {
      const session = state.sessions[action.key] ?? createSessionEntry(action.key);
      const msgs = [...session.messages];
      let last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") {
        msgs.push({ role: "assistant", content: "", events: [], capability: session.activeCapability || "" });
        last = msgs[msgs.length - 1];
      }
      const events = [...(last?.events || []), action.event];
      let content = last?.content || "";
      if (shouldAppendEventContent(action.event)) content += action.event.content;
      const capability = last?.capability || session.activeCapability || "";
      msgs[msgs.length - 1] = { ...(last || { role: "assistant", content: "" }), content, events, capability };
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: msgs,
            currentStage:
              action.event.type === "stage_start"
                ? action.event.stage
                : action.event.type === "stage_end"
                  ? ""
                  : session.currentStage,
            activeTurnId: action.event.turn_id || session.activeTurnId,
            lastSeq: Math.max(session.lastSeq, action.event.seq || 0),
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "STREAM_END":
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...(state.sessions[action.key] ?? createSessionEntry(action.key)),
            isStreaming: false,
            currentStage: "",
            status: action.status ?? "completed",
            activeTurnId:
              action.status === "running"
                ? action.turnId || state.sessions[action.key]?.activeTurnId || null
                : null,
            updatedAt: Date.now(),
          },
        },
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    case "BIND_SERVER_SESSION": {
      const current = state.sessions[action.key] ?? createSessionEntry(action.key);
      const targetKey = action.sessionId;
      const existing = state.sessions[targetKey];
      const merged: SessionEntry = {
        ...(existing ?? current),
        ...current,
        key: targetKey,
        sessionId: action.sessionId,
        activeTurnId: action.turnId || current.activeTurnId,
        status: current.isStreaming ? "running" : current.status,
        updatedAt: Date.now(),
      };
      const nextSessions = { ...state.sessions };
      delete nextSessions[action.key];
      nextSessions[targetKey] = merged;
      return {
        ...state,
        selectedKey: state.selectedKey === action.key ? targetKey : state.selectedKey,
        sessions: nextSessions,
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    }
    case "LOAD_SESSION": {
      const existing = state.sessions[action.key] ?? createSessionEntry(action.key, action.sessionId);
      return {
        ...state,
        selectedKey: action.key,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...existing,
            key: action.key,
            sessionId: action.sessionId,
            enabledTools: action.tools ?? existing.enabledTools,
            activeCapability:
              action.capability !== undefined ? action.capability : existing.activeCapability,
            knowledgeBases: action.knowledgeBases ?? existing.knowledgeBases,
            messages: action.messages,
            isStreaming: (action.status || "idle") === "running",
            currentStage: "",
            activeTurnId: action.activeTurnId || null,
            status: action.status || "idle",
            language: action.language ?? existing.language,
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "NEW_SESSION": {
      const MAX_CACHED_SESSIONS = 20;
      let nextSessions = { ...state.sessions, [action.key]: createSessionEntry(action.key) };
      const keys = Object.keys(nextSessions);
      if (keys.length > MAX_CACHED_SESSIONS) {
        const evictable = keys
          .filter((k) => k !== action.key && nextSessions[k].status !== "running")
          .sort((a, b) => nextSessions[a].updatedAt - nextSessions[b].updatedAt);
        const toRemove = evictable.slice(0, keys.length - MAX_CACHED_SESSIONS);
        for (const k of toRemove) delete nextSessions[k];
      }
      return { ...state, selectedKey: action.key, sessions: nextSessions };
    }
    default:
      return state;
  }
}

const initialState: ProviderState = {
  selectedKey: null,
  sessions: {},
  sidebarRefreshToken: 0,
};

interface ChatContextValue {
  state: ChatState;
  setTools: (tools: string[]) => void;
  setCapability: (cap: string | null) => void;
  setKBs: (kbs: string[]) => void;
  setLanguage: (lang: string) => void;
  sendMessage: (
    content: string,
    attachments?: OutgoingAttachment[],
    config?: Record<string, unknown>,
    notebookReferences?: NotebookReferencePayload[],
    historyReferences?: HistoryReferencePayload,
    options?: SendMessageOptions,
  ) => void;
  cancelStreamingTurn: () => void;
  newSession: () => void;
  loadSession: (sessionId: string) => Promise<void>;
  selectedSessionId: string | null;
  sessionStatuses: Record<string, SessionStatusSnapshot>;
  sidebarRefreshToken: number;
}

const ChatCtx = createContext<ChatContextValue | null>(null);

export function UnifiedChatProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(initialState);
  const runnersRef = useRef<
    Map<
      string,
      {
        key: string;
        client: UnifiedWSClient;
      }
    >
  >(new Map());
  const draftCounterRef = useRef(0);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(
    () => () => {
      runnersRef.current.forEach(({ client }) => client.disconnect());
      runnersRef.current.clear();
      retryTimersRef.current.forEach((id) => clearTimeout(id));
      retryTimersRef.current.clear();
    },
    [],
  );

  const makeDraftKey = useCallback(() => {
    draftCounterRef.current += 1;
    return `draft_${Date.now()}_${draftCounterRef.current}`;
  }, []);

  const hydrateMessages = useCallback((messages: SessionMessage[]): MessageItem[] => {
    return messages.map((message) => ({
      role: message.role,
      content:
        message.role === "assistant"
          ? normalizeMarkdownForDisplay(message.content)
          : message.content,
      capability: message.capability || "",
      events: Array.isArray(message.events) ? message.events : [],
      attachments: Array.isArray(message.attachments)
        ? message.attachments.map((item) => ({
            type: item.type,
            filename: item.filename,
            base64: item.base64,
            url: item.url,
            mime_type: item.mime_type,
          }))
        : [],
    }));
  }, []);

  const moveRunner = useCallback((oldKey: string, newKey: string) => {
    if (oldKey === newKey) return;
    const runner = runnersRef.current.get(oldKey);
    if (!runner) return;
    runnersRef.current.delete(oldKey);
    runner.key = newKey;
    runnersRef.current.set(newKey, runner);
  }, []);

  const handleRunnerEvent = useCallback(
    (runnerKey: string, event: StreamEvent) => {
      const runner = runnersRef.current.get(runnerKey);
      const effectiveKey = runner?.key || runnerKey;
      if (event.type === "session") {
        const sessionId =
          (event.metadata as { session_id?: string } | undefined)?.session_id ||
          event.session_id ||
          "";
        const turnId =
          (event.metadata as { turn_id?: string } | undefined)?.turn_id || event.turn_id || null;
        if (sessionId) {
          dispatch({
            type: "BIND_SERVER_SESSION",
            key: effectiveKey,
            sessionId,
            turnId,
          });
          moveRunner(effectiveKey, sessionId);
        }
        return;
      }
      if (event.type === "done") {
        const status = String((event.metadata as { status?: string } | undefined)?.status || "completed");
        dispatch({
          type: "STREAM_END",
          key: effectiveKey,
          status: (status as SessionRuntimeStatus) || "completed",
          turnId: event.turn_id || null,
        });
        const runner = runnersRef.current.get(effectiveKey);
        runner?.client.disconnect();
        runnersRef.current.delete(effectiveKey);
        return;
      }
      dispatch({ type: "STREAM_EVENT", key: effectiveKey, event });
      if (
        event.type === "error" &&
        Boolean((event.metadata as { turn_terminal?: boolean } | undefined)?.turn_terminal)
      ) {
        const status = String((event.metadata as { status?: string } | undefined)?.status || "failed");
        dispatch({
          type: "STREAM_END",
          key: effectiveKey,
          status: status as SessionRuntimeStatus,
          turnId: event.turn_id || null,
        });
      }
    },
    [moveRunner],
  );

  const ensureRunner = useCallback(
    (key: string) => {
      const existing = runnersRef.current.get(key);
      if (existing) {
        const session = stateRef.current.sessions[key];
        if (session) {
          existing.client.setResumeState(session.activeTurnId, session.lastSeq);
        }
        if (!existing.client.connected) existing.client.connect();
        return existing;
      }
      const record = {
        key,
        client: new UnifiedWSClient(
          (event) => handleRunnerEvent(record.key, event),
          () => {
            const session = stateRef.current.sessions[record.key];
            if (session?.isStreaming) {
              dispatch({ type: "STREAM_END", key: record.key, status: "failed" });
            }
          },
        ),
      };
      runnersRef.current.set(key, record);
      record.client.connect();
      return record;
    },
    [handleRunnerEvent],
  );

  const sendThroughRunner = useCallback(
    function dispatchToRunner(key: string, msg: ChatMessage, attempt = 0) {
      const runner = ensureRunner(key);
      if (!runner.client.connected) {
        if (attempt >= 10) {
          console.error("WebSocket failed to connect after retries");
          dispatch({ type: "STREAM_END", key, status: "failed" });
          return;
        }
        const timerId = setTimeout(() => {
          retryTimersRef.current.delete(timerId);
          dispatchToRunner(key, msg, attempt + 1);
        }, 200);
        retryTimersRef.current.add(timerId);
        return;
      }
      runner.client.send(msg);
    },
    [ensureRunner],
  );

  const loadSession = useCallback(
    async (sessionId: string) => {
      const session = await getSession(sessionId);
      const activeTurn = Array.isArray(session.active_turns) ? session.active_turns[0] : undefined;
      dispatch({
        type: "LOAD_SESSION",
        key: session.session_id || session.id,
        sessionId: session.session_id || session.id,
        messages: hydrateMessages(session.messages ?? []),
        activeTurnId: activeTurn?.turn_id || activeTurn?.id || null,
        status: (session.status as SessionRuntimeStatus | undefined) || (activeTurn ? "running" : "idle"),
        tools: Array.isArray(session.preferences?.tools) ? session.preferences.tools : [],
        capability: session.preferences?.capability || null,
        knowledgeBases: Array.isArray(session.preferences?.knowledge_bases)
          ? session.preferences.knowledge_bases
          : [],
        language: session.preferences?.language || "en",
      });
      if (activeTurn?.turn_id || activeTurn?.id) {
        const key = session.session_id || session.id;
        sendThroughRunner(key, {
          type: "subscribe_turn",
          turn_id: activeTurn.turn_id || activeTurn.id,
          after_seq: 0,
        });
      }
    },
    [hydrateMessages, sendThroughRunner],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const current = state.selectedKey ? state.sessions[state.selectedKey] : null;
    writeStoredActiveSessionId(current?.sessionId ?? null);
  }, [state.selectedKey, state.sessions]);

  // URL is now the source of truth for session loading.
  // Chat pages load sessions based on URL params; no sessionStorage restore needed.
  // Initialize a draft session so the provider always has a selected key.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!state.selectedKey) {
      dispatch({ type: "NEW_SESSION", key: makeDraftKey() });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Idle timeout: if a streaming session receives no events for 60s, auto-fail it.
  useEffect(() => {
    const IDLE_TIMEOUT_MS = 60_000;
    const CHECK_INTERVAL_MS = 10_000;

    const timer = setInterval(() => {
      const current = stateRef.current;
      for (const [key, session] of Object.entries(current.sessions)) {
        if (!session.isStreaming) continue;
        if (Date.now() - session.updatedAt <= IDLE_TIMEOUT_MS) continue;

        dispatch({
          type: "STREAM_EVENT",
          key,
          event: {
            type: "error",
            source: "client",
            stage: "",
            content: "Connection timed out — no response received for 60 seconds.",
            metadata: { turn_terminal: true, status: "failed" },
            timestamp: Date.now() / 1000,
          },
        });
        dispatch({ type: "STREAM_END", key, status: "failed" });

        const runner = runnersRef.current.get(key);
        if (runner) {
          runner.client.disconnect();
          runnersRef.current.delete(key);
        }
      }
    }, CHECK_INTERVAL_MS);

    return () => clearInterval(timer);
  }, []);

  const sendMessage = useCallback(
    (
      content: string,
      attachments?: OutgoingAttachment[],
      config?: Record<string, unknown>,
      notebookReferences?: NotebookReferencePayload[],
      historyReferences?: HistoryReferencePayload,
      options?: SendMessageOptions,
    ) => {
      const msgAttachments = attachments?.map((a) => ({
        type: a.type,
        filename: a.filename,
        base64: a.base64,
        url: a.url,
        mime_type: a.mime_type,
      }));
      const currentState = stateRef.current;
      let key = currentState.selectedKey;
      if (!key) {
        key = makeDraftKey();
        dispatch({ type: "NEW_SESSION", key });
      }
      const session = currentState.sessions[key] ?? createSessionEntry(key);
      const replaySnapshot = options?.requestSnapshotOverride;
      const effectiveCapability = replaySnapshot?.capability ?? session.activeCapability;
      const effectiveTools = replaySnapshot?.enabledTools ?? session.enabledTools;
      const effectiveKnowledgeBases = replaySnapshot?.knowledgeBases ?? session.knowledgeBases;
      const effectiveLanguage = replaySnapshot?.language ?? session.language;
      const researchSources = Array.isArray(config?.sources)
        ? config.sources.filter((value): value is string => typeof value === "string")
        : [];
      const shouldSendKnowledgeBases =
        effectiveTools.includes("rag") ||
        (effectiveCapability === "deep_research" && researchSources.includes("kb"));
      const requestSnapshot: MessageRequestSnapshot = replaySnapshot ?? {
        content,
        capability: effectiveCapability,
        enabledTools: [...effectiveTools],
        knowledgeBases: shouldSendKnowledgeBases ? [...effectiveKnowledgeBases] : [],
        language: effectiveLanguage,
        ...(msgAttachments?.length ? { attachments: msgAttachments } : {}),
        ...(config && Object.keys(config).length > 0 ? { config } : {}),
        ...(notebookReferences?.length ? { notebookReferences } : {}),
        ...(historyReferences?.length ? { historyReferences: [...historyReferences] } : {}),
      };
      if (options?.displayUserMessage !== false) {
        dispatch({
          type: "ADD_USER_MSG",
          key,
          content,
          capability: effectiveCapability,
          attachments: msgAttachments,
          requestSnapshot,
        });
      }
      dispatch({ type: "STREAM_START", key });
      const effectiveConfig =
        options?.persistUserMessage === false
          ? { ...(config || {}), _persist_user_message: false }
          : config;
      sendThroughRunner(key, {
        type: "start_turn",
        content,
        tools: effectiveTools,
        capability: effectiveCapability,
        knowledge_bases: shouldSendKnowledgeBases ? effectiveKnowledgeBases : [],
        session_id: session.sessionId,
        attachments,
        language: effectiveLanguage,
        ...(notebookReferences?.length
          ? { notebook_references: notebookReferences }
          : {}),
        ...(historyReferences?.length
          ? { history_references: historyReferences }
          : {}),
        ...(effectiveConfig && Object.keys(effectiveConfig).length > 0
          ? { config: effectiveConfig }
          : {}),
      });
    },
    [makeDraftKey, sendThroughRunner],
  );

  const cancelStreamingTurn = useCallback(() => {
    const currentState = stateRef.current;
    const key = currentState.selectedKey;
    if (!key) return;
    const session = currentState.sessions[key];
    const turnId = session?.activeTurnId;
    if (!session || !turnId) return;
    const runner = runnersRef.current.get(key);
    if (runner?.client.connected) {
      runner.client.send({ type: "cancel_turn", turn_id: turnId });
      runner.client.disconnect();
      runnersRef.current.delete(key);
    }
    dispatch({ type: "STREAM_END", key, status: "cancelled" });
  }, []);

  const derivedState = useMemo<ChatState>(() => {
    const current = ensureSelectedSession(state);
    return {
      sessionId: current.sessionId,
      enabledTools: current.enabledTools,
      activeCapability: current.activeCapability,
      knowledgeBases: current.knowledgeBases,
      messages: current.messages,
      isStreaming: current.isStreaming,
      currentStage: current.currentStage,
      language: current.language,
    };
  }, [state]);

  const sessionStatuses = useMemo<Record<string, SessionStatusSnapshot>>(() => {
    const entries: Record<string, SessionStatusSnapshot> = {};
    for (const session of Object.values(state.sessions)) {
      if (!session.sessionId || session.status !== "running") continue;
      entries[session.sessionId] = {
        sessionId: session.sessionId,
        status: session.status,
        activeTurnId: session.activeTurnId,
        updatedAt: session.updatedAt,
      };
    }
    return entries;
  }, [state.sessions]);

  const setTools = useCallback((tools: string[]) => {
    dispatch({ type: "SET_TOOLS", tools });
  }, []);

  const setCapability = useCallback((cap: string | null) => {
    dispatch({ type: "SET_CAPABILITY", cap });
  }, []);

  const setKBs = useCallback((kbs: string[]) => {
    dispatch({ type: "SET_KB", kbs });
  }, []);

  const setLanguage = useCallback((lang: string) => {
    dispatch({ type: "SET_LANGUAGE", lang });
  }, []);

  const newSession = useCallback(() => {
    dispatch({ type: "NEW_SESSION", key: makeDraftKey() });
  }, [makeDraftKey]);

  const value: ChatContextValue = {
    state: derivedState,
    setTools,
    setCapability,
    setKBs,
    setLanguage,
    sendMessage,
    cancelStreamingTurn,
    newSession,
    loadSession,
    selectedSessionId: derivedState.sessionId,
    sessionStatuses,
    sidebarRefreshToken: state.sidebarRefreshToken,
  };

  return <ChatCtx.Provider value={value}>{children}</ChatCtx.Provider>;
}

export function useUnifiedChat() {
  const ctx = useContext(ChatCtx);
  if (!ctx) throw new Error("useUnifiedChat must be inside UnifiedChatProvider");
  return ctx;
}
