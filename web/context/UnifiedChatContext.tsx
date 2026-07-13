"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import {
  LANGUAGE_EVENT,
  LANGUAGE_STORAGE_KEY,
  normalizeLanguage,
  readStoredChatResponseTimeout,
  readStoredLanguage,
  writeStoredActiveSessionId,
} from "@/context/app-shell-storage";
import type { StreamEvent, ChatMessage, LLMSelection } from "@/lib/unified-ws";
import { UnifiedWSClient } from "@/lib/unified-ws";
import {
  getSession,
  deleteMessage,
  updateBranchSelection,
  updateSessionTitle,
  type SessionMessage,
} from "@/lib/session-api";
import { normalizeMarkdownForDisplay } from "@/lib/markdown-display";
import { normalizeMessageContent } from "@/lib/message-content";
import { buildVisiblePath, tipMessageId } from "@/lib/message-branches";
import {
  isNarrationMarker,
  recomputeAnswerContent,
  shouldAppendEventContent,
} from "@/lib/stream";
import { hasPendingAskUserInMessages } from "@/lib/ask-user-state";
import { notify } from "@/lib/notifications";
import i18n from "i18next";
import {
  normalizeBookReferences,
  type BookReferencePayload,
} from "@/lib/book-references";

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

type QuestionNotebookReferencePayload = number[];

type MemoryReferencePayload = Array<"summary" | "profile">;

export interface SendMessageOptions {
  displayUserMessage?: boolean;
  persistUserMessage?: boolean;
  requestSnapshotOverride?: MessageRequestSnapshot;
  bookReferences?: BookReferencePayload[];
  /** Edit-branching: when set, the new user message is inserted as a
   *  sibling under this parent rather than appended to the session tail.
   *  ``null`` means "explicitly attach to the session root". */
  parentMessageId?: number | null;
}

export interface ChatState {
  sessionId: string | null;
  sessionTitle: string;
  enabledTools: string[];
  activeCapability: string | null;
  knowledgeBases: string[];
  llmSelection: LLMSelection | null;
  /** Session-level persona preference; "" = Default (no persona). Applies
   *  to every following message until changed (persisted on the session). */
  personaSelection: string;
  messages: MessageItem[];
  isStreaming: boolean;
  currentStage: string;
  language: string;
  /** Edit-branching: keyed by stringified parent_message_id (or "null"
   *  for the root). Empty means "default to latest sibling everywhere". */
  selectedBranches: Record<string, number>;
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
  /** Stable per-attachment id; matches the URL segment served by /api/attachments. */
  id?: string;
  /** Plain-text rendering of office docs, populated by the backend extractor.
   *  Used by the preview drawer to show "what the LLM saw" for binary docs. */
  extracted_text?: string;
  /** Set on files the assistant produced this turn (exec/code_execution
   *  artifacts) rather than files the user uploaded. Rendered as openable
   *  cards under the assistant message. */
  generated?: boolean;
  /** Byte size of the generated file, for the card's subtitle. */
  size_bytes?: number;
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
  questionNotebookReferences?: QuestionNotebookReferencePayload;
  bookReferences?: BookReferencePayload[];
  persona?: string;
  memoryReferences?: MemoryReferencePayload;
  llmSelection?: LLMSelection | null;
}

export interface MessageItem {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
  events?: StreamEvent[];
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
  /** Edit-branching: id of the message this row continues. */
  parentMessageId?: number | null;
}

interface SessionEntry extends ChatState {
  key: string;
  status: SessionRuntimeStatus;
  activeTurnId: string | null;
  lastSeq: number;
  updatedAt: number;
  /** Edit-branching: maps a parent_message_id (stringified, or "null" for
   *  the session root) to the chosen child id at that branch point. */
  selectedBranches: Record<string, number>;
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
  | { type: "SET_LLM_SELECTION"; selection: LLMSelection | null }
  | { type: "SET_PERSONA_SELECTION"; persona: string }
  | { type: "SET_LANGUAGE"; lang: string }
  | {
      type: "ADD_USER_MSG";
      key: string;
      content: string;
      capability?: string | null;
      attachments?: MessageAttachment[];
      requestSnapshot?: MessageRequestSnapshot;
      parentMessageId?: number | null;
    }
  | { type: "POP_LAST_ASSISTANT"; key: string }
  | { type: "RESTORE_ASSISTANT"; key: string; message: MessageItem }
  | { type: "STREAM_START"; key: string }
  | { type: "STREAM_EVENT"; key: string; event: StreamEvent }
  | {
      type: "STREAM_END";
      key: string;
      status?: SessionRuntimeStatus;
      turnId?: string | null;
    }
  | {
      type: "BIND_SERVER_SESSION";
      key: string;
      sessionId: string;
      turnId?: string | null;
    }
  | {
      type: "LOAD_SESSION";
      key: string;
      sessionId: string;
      title?: string;
      messages: MessageItem[];
      activeTurnId?: string | null;
      status?: SessionRuntimeStatus;
      tools?: string[];
      capability?: string | null;
      knowledgeBases?: string[];
      llmSelection?: LLMSelection | null;
      personaSelection?: string;
      language?: string;
      selectedBranches?: Record<string, number>;
    }
  | { type: "SET_SESSION_TITLE"; key: string; title: string }
  | { type: "DELETE_TURN"; key: string; messageId: number }
  | { type: "NEW_SESSION"; key: string }
  | {
      type: "SET_SELECTED_BRANCH";
      key: string;
      parentKey: string;
      childId: number;
    }
  | {
      type: "REPLACE_SELECTED_BRANCHES";
      key: string;
      selectedBranches: Record<string, number>;
    }
  | { type: "BUMP_SIDEBAR_REFRESH" };

function createSessionEntry(
  key: string,
  sessionId: string | null = null,
): SessionEntry {
  return {
    key,
    sessionId,
    sessionTitle: "",
    enabledTools: [],
    activeCapability: null,
    knowledgeBases: [],
    llmSelection: null,
    personaSelection: "",
    messages: [],
    isStreaming: false,
    currentStage: "",
    language: typeof window === "undefined" ? "en" : readStoredLanguage(),
    status: "idle",
    activeTurnId: null,
    lastSeq: 0,
    updatedAt: Date.now(),
    selectedBranches: {},
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

function isSameTurnEvent(a: StreamEvent, b: StreamEvent): boolean {
  const aSeq = Number(a.seq || 0);
  const bSeq = Number(b.seq || 0);
  if (aSeq <= 0 || bSeq <= 0 || aSeq !== bSeq) return false;
  const aTurn = a.turn_id || "";
  const bTurn = b.turn_id || "";
  return Boolean(aTurn && bTurn && aTurn === bTurn);
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
    case "SET_LLM_SELECTION":
      return updateSelectedSession(state, (session) => ({
        ...session,
        llmSelection: action.selection,
      }));
    case "SET_PERSONA_SELECTION":
      return updateSelectedSession(state, (session) => ({
        ...session,
        personaSelection: action.persona,
      }));
    case "SET_LANGUAGE":
      return updateSelectedSession(state, (session) => ({
        ...session,
        language: action.lang,
      }));
    case "ADD_USER_MSG": {
      const session =
        state.sessions[action.key] ?? createSessionEntry(action.key);
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: [
              ...session.messages,
              {
                id: -Date.now(),
                role: "user",
                content: action.content,
                capability: action.capability || "",
                parentMessageId:
                  action.parentMessageId === undefined
                    ? null
                    : action.parentMessageId,
                ...(action.attachments?.length
                  ? { attachments: action.attachments }
                  : {}),
                ...(action.requestSnapshot
                  ? { requestSnapshot: action.requestSnapshot }
                  : {}),
              },
            ],
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "POP_LAST_ASSISTANT": {
      const session = state.sessions[action.key];
      if (!session || session.messages.length === 0) return state;
      const last = session.messages[session.messages.length - 1];
      if (last.role !== "assistant") return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: session.messages.slice(0, -1),
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "RESTORE_ASSISTANT": {
      // Revert an optimistic POP_LAST_ASSISTANT when the server rejects a
      // regenerate request (e.g. ``regenerate_busy``), so the user doesn't
      // silently lose their last reply.
      const session = state.sessions[action.key];
      if (!session) return state;
      const messages = [...session.messages];
      // Drop any placeholder STREAM_START assistant bubble before restoring.
      while (
        messages.length > 0 &&
        messages[messages.length - 1].role === "assistant" &&
        (messages[messages.length - 1].content ?? "") === "" &&
        (messages[messages.length - 1].events?.length ?? 0) === 0
      ) {
        messages.pop();
      }
      messages.push(action.message);
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages,
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "STREAM_START": {
      const session =
        state.sessions[action.key] ?? createSessionEntry(action.key);
      const existing = session.messages ?? [];
      // Chain the placeholder assistant onto whatever message currently
      // sits at the tip — this is normally the user row just added by
      // ADD_USER_MSG (possibly an optimistic negative id during an edit).
      const tip = existing.length > 0 ? existing[existing.length - 1] : null;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            isStreaming: true,
            status: "running",
            messages: [
              ...existing,
              {
                id: -Date.now(),
                role: "assistant",
                content: "",
                events: [],
                capability: session.activeCapability || "",
                parentMessageId: tip?.id ?? null,
              },
            ],
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "STREAM_EVENT": {
      // If the session entry has been removed (e.g., BIND_SERVER_SESSION
      // just renamed ``draft_X`` to a real id but a stray event still
      // targets the old key), drop the event rather than synthesise an
      // orphan session with no user message — that would scrub the
      // user's just-sent bubble from view.
      if (!state.sessions[action.key]) return state;
      const session = state.sessions[action.key];
      const msgs = [...session.messages];
      let last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") {
        msgs.push({
          id: -Date.now(),
          role: "assistant",
          content: "",
          events: [],
          capability: session.activeCapability || "",
          parentMessageId: last?.id ?? null,
        });
        last = msgs[msgs.length - 1];
      }
      if (
        (last?.events || []).some((event) =>
          isSameTurnEvent(event, action.event),
        )
      ) {
        return state;
      }
      const events = [...(last?.events || []), action.event];
      let content = last?.content || "";
      if (isNarrationMarker(action.event)) {
        // A round just resolved as narration (preamble before a tool call):
        // drop its already-streamed text from the answer — it stays in the
        // trace. Recomputing is cheap here (only fires per narration round).
        content = recomputeAnswerContent(events);
      } else if (shouldAppendEventContent(action.event)) {
        content += action.event.content;
      }
      const capability = last?.capability || session.activeCapability || "";
      msgs[msgs.length - 1] = {
        ...(last || { role: "assistant", content: "" }),
        content,
        events,
        capability,
      };
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
                ? action.turnId ||
                  state.sessions[action.key]?.activeTurnId ||
                  null
                : null,
            updatedAt: Date.now(),
          },
        },
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    case "BIND_SERVER_SESSION": {
      const current =
        state.sessions[action.key] ?? createSessionEntry(action.key);
      const targetKey = action.sessionId;
      const existing = state.sessions[targetKey];
      const merged: SessionEntry = {
        ...(existing ?? current),
        ...current,
        key: targetKey,
        sessionId: action.sessionId,
        sessionTitle: current.sessionTitle || existing?.sessionTitle || "",
        activeTurnId: action.turnId || current.activeTurnId,
        status: current.isStreaming ? "running" : current.status,
        updatedAt: Date.now(),
      };
      const nextSessions = { ...state.sessions };
      delete nextSessions[action.key];
      nextSessions[targetKey] = merged;
      return {
        ...state,
        selectedKey:
          state.selectedKey === action.key ? targetKey : state.selectedKey,
        sessions: nextSessions,
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    }
    case "LOAD_SESSION": {
      const existing =
        state.sessions[action.key] ??
        createSessionEntry(action.key, action.sessionId);
      return {
        ...state,
        selectedKey: action.key,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...existing,
            key: action.key,
            sessionId: action.sessionId,
            sessionTitle:
              action.title !== undefined ? action.title : existing.sessionTitle,
            enabledTools: action.tools ?? existing.enabledTools,
            activeCapability:
              action.capability !== undefined
                ? action.capability
                : existing.activeCapability,
            knowledgeBases: action.knowledgeBases ?? existing.knowledgeBases,
            llmSelection:
              action.llmSelection !== undefined
                ? action.llmSelection
                : existing.llmSelection,
            personaSelection:
              action.personaSelection !== undefined
                ? action.personaSelection
                : existing.personaSelection,
            messages: action.messages,
            isStreaming: (action.status || "idle") === "running",
            currentStage: "",
            activeTurnId: action.activeTurnId || null,
            status: action.status || "idle",
            language: action.language ?? existing.language,
            selectedBranches:
              action.selectedBranches ?? existing.selectedBranches,
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "SET_SESSION_TITLE": {
      const session = state.sessions[action.key];
      if (!session) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            sessionTitle: action.title,
            updatedAt: Date.now(),
          },
        },
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    }
    case "SET_SELECTED_BRANCH": {
      const session = state.sessions[action.key];
      if (!session) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            selectedBranches: {
              ...session.selectedBranches,
              [action.parentKey]: action.childId,
            },
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "REPLACE_SELECTED_BRANCHES": {
      const session = state.sessions[action.key];
      if (!session) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            selectedBranches: { ...action.selectedBranches },
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "DELETE_TURN": {
      const session = state.sessions[action.key];
      if (!session) return state;
      const idx = session.messages.findIndex((m) => m.id === action.messageId);
      if (idx === -1) return state;
      const msg = session.messages[idx];
      const toRemove = new Set<number>();
      toRemove.add(idx);
      if (msg.role === "user") {
        if (
          idx + 1 < session.messages.length &&
          session.messages[idx + 1].role === "assistant"
        ) {
          toRemove.add(idx + 1);
        }
      } else if (msg.role === "assistant") {
        if (idx - 1 >= 0 && session.messages[idx - 1].role === "user") {
          toRemove.add(idx - 1);
        }
      }
      const nextMessages = session.messages.filter((_, i) => !toRemove.has(i));
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: nextMessages,
            isStreaming: false,
            status: "idle",
            updatedAt: Date.now(),
          },
        },
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    }
    case "BUMP_SIDEBAR_REFRESH":
      return {
        ...state,
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    case "NEW_SESSION": {
      const MAX_CACHED_SESSIONS = 20;
      let nextSessions = {
        ...state.sessions,
        [action.key]: createSessionEntry(action.key),
      };
      const keys = Object.keys(nextSessions);
      if (keys.length > MAX_CACHED_SESSIONS) {
        const evictable = keys
          .filter(
            (k) => k !== action.key && nextSessions[k].status !== "running",
          )
          .sort(
            (a, b) => nextSessions[a].updatedAt - nextSessions[b].updatedAt,
          );
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

// Grace window between the orchestrator's ``done`` event and the actual
// WS disconnect. Keeps the connection alive long enough for post-turn
// pushes like the LLM-generated ``session_meta`` title update to land.
const POST_DONE_DISCONNECT_DELAY_MS = 15_000;

interface ChatContextValue {
  state: ChatState;
  setTools: (tools: string[]) => void;
  setCapability: (cap: string | null) => void;
  setKBs: (kbs: string[]) => void;
  setLLMSelection: (selection: LLMSelection | null) => void;
  setPersonaSelection: (persona: string) => void;
  setLanguage: (lang: string) => void;
  sendMessage: (
    content: string,
    attachments?: OutgoingAttachment[],
    config?: Record<string, unknown>,
    notebookReferences?: NotebookReferencePayload[],
    historyReferences?: HistoryReferencePayload,
    options?: SendMessageOptions,
    questionNotebookReferences?: QuestionNotebookReferencePayload,
    persona?: string,
    memoryReferences?: MemoryReferencePayload,
  ) => void;
  cancelStreamingTurn: () => void;
  /**
   * Deliver the user's reply for a turn that is paused on an
   * ``ask_user`` tool call. Sends the reply via the unified WS so the
   * backend can substitute it into the matching ``role=tool`` message
   * and resume the agentic loop on the **same** turn. No-op when the
   * active session has no live turn waiting on input.
   *
   * Accepts a plain string (legacy single-question reply) or a
   * structured object with ``answers`` (v2 multi-question reply).
   */
  submitUserReply: (
    reply:
      | string
      | {
          text?: string;
          answers?: Array<{ questionId: string; text: string }>;
        },
  ) => void;
  regenerateLastMessage: () => void;
  deleteTurn: (messageId: number) => Promise<void>;
  /** Re-send a user message under a new branch (sibling of the original).
   *  Uses the composer's current capability / refs — only the text is
   *  taken from ``newContent``. Re-runs the turn from the original's
   *  parent context. */
  editMessage: (messageId: number, newContent: string) => Promise<void>;
  /** Switch which sibling is currently visible at a branch point. */
  switchBranch: (parentMessageId: number | null, childId: number) => void;
  renameSessionTitle: (title: string) => Promise<void>;
  newSession: () => void;
  loadSession: (sessionId: string, signal?: AbortSignal) => Promise<void>;
  selectedSessionId: string | null;
  sessionStatuses: Record<string, SessionStatusSnapshot>;
  sidebarRefreshToken: number;
}

const ChatCtx = createContext<ChatContextValue | null>(null);

function hydrateMessageAttachments(
  attachments: SessionMessage["attachments"],
): MessageAttachment[] {
  return Array.isArray(attachments)
    ? attachments.map((item) => ({
        type: item.type,
        filename: item.filename,
        base64: item.base64,
        url: item.url,
        mime_type: item.mime_type,
        id: item.id,
        extracted_text: item.extracted_text,
        generated: item.generated,
        size_bytes: item.size_bytes,
      }))
    : [];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is string => typeof item === "string" && item.length > 0,
      )
    : [];
}

function asLLMSelection(value: unknown): LLMSelection | null {
  const record = asRecord(value);
  const profileId =
    typeof record?.profile_id === "string" ? record.profile_id.trim() : "";
  const modelId =
    typeof record?.model_id === "string" ? record.model_id.trim() : "";
  return profileId && modelId
    ? { profile_id: profileId, model_id: modelId }
    : null;
}

function normalizeSelectedBranches(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: Record<string, number> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    const n = typeof v === "number" ? v : Number(v);
    if (Number.isInteger(n) && n > 0) result[k] = n;
  }
  return result;
}

function asMemoryReferences(value: unknown): MemoryReferencePayload {
  return asStringArray(value).filter(
    (item): item is "summary" | "profile" =>
      item === "summary" || item === "profile",
  );
}

function asNotebookReferences(value: unknown): NotebookReferencePayload[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const ref = asRecord(item);
    const notebookId =
      typeof ref?.notebook_id === "string" ? ref.notebook_id : "";
    const recordIds = asStringArray(ref?.record_ids);
    return notebookId && recordIds.length
      ? [{ notebook_id: notebookId, record_ids: recordIds }]
      : [];
  });
}

function asQuestionReferences(
  value: unknown,
): QuestionNotebookReferencePayload {
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "number" ? item : Number(item)))
        .filter((item) => Number.isInteger(item))
    : [];
}

function hydrateRequestSnapshot(
  message: SessionMessage,
  content: string,
  attachments: MessageAttachment[],
): MessageRequestSnapshot | undefined {
  const metadata = asRecord(message.metadata);
  const stored = asRecord(
    metadata?.request_snapshot ?? metadata?.requestSnapshot,
  );
  if (!stored) return undefined;

  const snapshot: MessageRequestSnapshot = {
    content: typeof stored.content === "string" ? stored.content : content,
    capability:
      typeof stored.capability === "string"
        ? stored.capability
        : message.capability || "",
    enabledTools: asStringArray(stored.enabledTools),
    knowledgeBases: asStringArray(stored.knowledgeBases),
    language: typeof stored.language === "string" ? stored.language : "en",
    ...(attachments.length ? { attachments } : {}),
  };

  const config = asRecord(stored.config);
  const notebookReferences = asNotebookReferences(stored.notebookReferences);
  const historyReferences = asStringArray(stored.historyReferences);
  const questionNotebookReferences = asQuestionReferences(
    stored.questionNotebookReferences,
  );
  const persona =
    typeof stored.persona === "string" && stored.persona.length > 0
      ? stored.persona
      : "";
  const memoryReferences = asMemoryReferences(stored.memoryReferences);
  const bookReferences = normalizeBookReferences(stored.bookReferences);
  const llmSelection = asLLMSelection(stored.llmSelection);

  if (config && Object.keys(config).length) snapshot.config = config;
  if (notebookReferences.length)
    snapshot.notebookReferences = notebookReferences;
  if (historyReferences.length) snapshot.historyReferences = historyReferences;
  if (questionNotebookReferences.length) {
    snapshot.questionNotebookReferences = questionNotebookReferences;
  }
  if (bookReferences.length) snapshot.bookReferences = bookReferences;
  if (persona) snapshot.persona = persona;
  if (memoryReferences.length) snapshot.memoryReferences = memoryReferences;
  if (llmSelection) snapshot.llmSelection = llmSelection;
  return snapshot;
}

export function UnifiedChatProvider({
  children,
}: {
  children: React.ReactNode;
}) {
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
  // Tracks in-flight regenerate requests so we can restore the popped
  // assistant message if the server rejects the request (e.g. ``regenerate_busy``
  // or ``nothing_to_regenerate``). Keyed by session entry key.
  const pendingRegenerateRef = useRef<Map<string, MessageItem>>(new Map());
  // Forward-declared so ``handleRunnerEvent`` (created above
  // ``loadSession`` in source order) can trigger a server refresh after
  // a turn finishes without taking a stale closure of ``loadSession``.
  const loadSessionRef = useRef<((sessionId: string) => Promise<void>) | null>(
    null,
  );

  useLayoutEffect(() => {
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

  const hydrateMessages = useCallback(
    (messages: SessionMessage[]): MessageItem[] => {
      return messages
        .filter((message) => message.role !== "system")
        .map((message) => {
          const raw = normalizeMessageContent(message.content as unknown);
          const attachments = hydrateMessageAttachments(message.attachments);
          const requestSnapshot = hydrateRequestSnapshot(
            message,
            raw,
            attachments,
          );
          return {
            id: message.id,
            role: message.role,
            content:
              message.role === "assistant"
                ? normalizeMarkdownForDisplay(raw)
                : raw,
            capability: message.capability || "",
            events: Array.isArray(message.events) ? message.events : [],
            attachments,
            parentMessageId:
              message.parent_message_id === undefined
                ? null
                : message.parent_message_id,
            ...(requestSnapshot ? { requestSnapshot } : {}),
          };
        });
    },
    [],
  );

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
          (event.metadata as { turn_id?: string } | undefined)?.turn_id ||
          event.turn_id ||
          null;
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
      if (event.type === "session_meta") {
        // Post-turn metadata push (currently only used for the
        // LLM-generated session title). The backend writes the new
        // title to its store *before* sending this event. Update the
        // active header immediately and bump the sidebar so history
        // rows refresh to the generated title without a flicker.
        const title = String(
          (event.metadata as { title?: string } | undefined)?.title || "",
        ).trim();
        if (title) {
          dispatch({
            type: "SET_SESSION_TITLE",
            key: effectiveKey,
            title,
          });
        } else {
          dispatch({ type: "BUMP_SIDEBAR_REFRESH" });
        }
        return;
      }
      if (event.type === "done") {
        const status = String(
          (event.metadata as { status?: string } | undefined)?.status ||
            "completed",
        );
        dispatch({
          type: "STREAM_END",
          key: effectiveKey,
          status: (status as SessionRuntimeStatus) || "completed",
          turnId: event.turn_id || null,
        });
        pendingRegenerateRef.current.delete(effectiveKey);
        const runner = runnersRef.current.get(effectiveKey);
        // Hold the WS open briefly so post-turn ``session_meta`` events
        // (e.g. the LLM-generated title for the first user/assistant
        // pair) can still reach us. The backend generates the title
        // before its finally block sends the subscriber sentinel, but
        // the title model can take a couple of seconds — disconnecting
        // synchronously on ``done`` would race that publish.
        if (runner) {
          runnersRef.current.delete(effectiveKey);
          window.setTimeout(() => {
            runner.client.disconnect();
          }, POST_DONE_DISCONNECT_DELAY_MS);
        }
        // Reconcile optimistic client-side message ids with the
        // server's real ids after the turn finishes. Without this the
        // Edit button (which needs a real id to attach the new branch
        // under) and branch navigation (which keys off real ids) would
        // stay disabled until the user navigates away and back.
        if (status === "completed") {
          const finishedSession = stateRef.current.sessions[effectiveKey];
          const sessionId = finishedSession?.sessionId;
          if (sessionId) {
            loadSessionRef.current?.(sessionId).catch(() => {
              /* non-fatal — local state remains usable */
            });
          }
        }
        return;
      }
      dispatch({ type: "STREAM_EVENT", key: effectiveKey, event });
      if (
        event.type === "error" &&
        Boolean(
          (event.metadata as { turn_terminal?: boolean } | undefined)
            ?.turn_terminal,
        )
      ) {
        const reason = String(
          (event.metadata as { reason?: string } | undefined)?.reason || "",
        );
        // Pre-flight regenerate rejections never mutate server state, so we
        // roll back the optimistic POP_LAST_ASSISTANT/STREAM_START placeholder
        // to keep the transcript in sync with the server.
        if (
          reason === "regenerate_busy" ||
          reason === "nothing_to_regenerate"
        ) {
          const stash = pendingRegenerateRef.current.get(effectiveKey);
          if (stash) {
            dispatch({
              type: "RESTORE_ASSISTANT",
              key: effectiveKey,
              message: stash,
            });
          }
        }
        pendingRegenerateRef.current.delete(effectiveKey);
        const status = String(
          (event.metadata as { status?: string } | undefined)?.status ||
            "failed",
        );
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
              if (
                hasPendingAskUserInMessages(
                  session.messages,
                  session.activeTurnId,
                )
              ) {
                return;
              }
              dispatch({
                type: "STREAM_END",
                key: record.key,
                status: "failed",
              });
              // Surface the disconnect to the user. The WS client already
              // logs to console — we add a toast so non-debugging users
              // don't see streaming silently flatline.
              notify(
                i18n.t(
                  "Connection lost while generating. Please retry your message.",
                ),
                { tone: "error", durationMs: 6000 },
              );
            }
          },
        ),
      };
      runnersRef.current.set(key, record);
      const session = stateRef.current.sessions[key];
      if (session?.activeTurnId) {
        record.client.setResumeState(session.activeTurnId, session.lastSeq);
      }
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
          // Surfaces the dead-after-N-retries case (different code path
          // from the close-while-streaming handler above). Same user
          // mental model, so same toast copy.
          notify(
            i18n.t(
              "Couldn't reach the server. Please check your connection and retry.",
            ),
            { tone: "error", durationMs: 6000 },
          );
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
    async (sessionId: string, signal?: AbortSignal) => {
      const session = await getSession(sessionId, signal);
      const activeTurn = Array.isArray(session.active_turns)
        ? session.active_turns[0]
        : undefined;
      dispatch({
        type: "LOAD_SESSION",
        key: session.session_id || session.id,
        sessionId: session.session_id || session.id,
        title: session.title || "",
        messages: hydrateMessages(session.messages ?? []),
        activeTurnId: activeTurn?.turn_id || activeTurn?.id || null,
        status:
          (session.status as SessionRuntimeStatus | undefined) ||
          (activeTurn ? "running" : "idle"),
        tools: Array.isArray(session.preferences?.tools)
          ? session.preferences.tools
          : [],
        capability: session.preferences?.capability || null,
        knowledgeBases: Array.isArray(session.preferences?.knowledge_bases)
          ? session.preferences.knowledge_bases
          : [],
        llmSelection: asLLMSelection(session.preferences?.llm_selection),
        personaSelection:
          typeof session.preferences?.persona === "string"
            ? session.preferences.persona
            : "",
        // The Settings language is global UI state. Historical sessions may
        // have stale persisted preferences, so new turns follow the current
        // app language rather than the language saved when the session began.
        language: readStoredLanguage(),
        selectedBranches: normalizeSelectedBranches(
          session.preferences?.selected_branches,
        ),
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

  useLayoutEffect(() => {
    loadSessionRef.current = loadSession;
  }, [loadSession]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const current = state.selectedKey
      ? state.sessions[state.selectedKey]
      : null;
    writeStoredActiveSessionId(current?.sessionId ?? null);
  }, [state.selectedKey, state.sessions]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const syncLanguage = (language: string | null | undefined) => {
      dispatch({ type: "SET_LANGUAGE", lang: normalizeLanguage(language) });
    };
    const onLanguage = (event: Event) => {
      const detail = (event as CustomEvent<{ language?: string }>).detail;
      syncLanguage(detail?.language);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === LANGUAGE_STORAGE_KEY) syncLanguage(event.newValue);
    };

    window.addEventListener(LANGUAGE_EVENT, onLanguage);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(LANGUAGE_EVENT, onLanguage);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  // URL is now the source of truth for session loading.
  // Chat pages load sessions based on URL params; no sessionStorage restore needed.
  // Initialize a draft session so the provider always has a selected key.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!state.selectedKey) {
      dispatch({ type: "NEW_SESSION", key: makeDraftKey() });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Idle timeout: if a streaming session receives no events for the configured
  // window (default 180s, set in Settings > Network), auto-fail it. Read per
  // tick so a settings change applies without remounting.
  useEffect(() => {
    const CHECK_INTERVAL_MS = 10_000;

    const timer = setInterval(() => {
      const timeoutSeconds = readStoredChatResponseTimeout();
      const idleTimeoutMs = timeoutSeconds * 1000;
      const current = stateRef.current;
      for (const [key, session] of Object.entries(current.sessions)) {
        if (!session.isStreaming) continue;
        if (
          hasPendingAskUserInMessages(session.messages, session.activeTurnId)
        ) {
          continue;
        }
        if (Date.now() - session.updatedAt <= idleTimeoutMs) continue;

        dispatch({
          type: "STREAM_EVENT",
          key,
          event: {
            type: "error",
            source: "client",
            stage: "",
            content: `Connection timed out — no response received for ${timeoutSeconds} seconds.`,
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
      questionNotebookReferences?: QuestionNotebookReferencePayload,
      persona?: string,
      memoryReferences?: MemoryReferencePayload,
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
      const effectiveCapability =
        replaySnapshot?.capability ?? session.activeCapability;
      const effectiveTools =
        replaySnapshot?.enabledTools ?? session.enabledTools;
      const effectiveKnowledgeBases =
        replaySnapshot?.knowledgeBases ?? session.knowledgeBases;
      const effectiveLLMSelection =
        replaySnapshot && "llmSelection" in replaySnapshot
          ? (replaySnapshot.llmSelection ?? null)
          : session.llmSelection;
      const effectiveLanguage =
        replaySnapshot?.language ?? readStoredLanguage();
      // Persona resolution: replay snapshot wins; then an explicit per-call
      // persona (quiz follow-up surface); then the session-level preference.
      // Always a string — "" means Default / no persona.
      const effectivePersona =
        replaySnapshot?.persona ?? persona ?? session.personaSelection ?? "";
      const effectiveMemoryReferences =
        replaySnapshot?.memoryReferences ?? memoryReferences;
      const effectiveBookReferences =
        replaySnapshot?.bookReferences ?? options?.bookReferences;
      const effectiveAttachments =
        replaySnapshot?.attachments?.map((a) => ({
          type: a.type,
          filename: a.filename,
          base64: a.base64,
          url: a.url,
          mime_type: a.mime_type,
        })) ?? msgAttachments;
      const effectiveConfig = config ?? replaySnapshot?.config;
      const effectiveNotebookReferences =
        replaySnapshot?.notebookReferences ?? notebookReferences;
      const effectiveHistoryReferences =
        replaySnapshot?.historyReferences ?? historyReferences;
      const effectiveQuestionNotebookReferences =
        replaySnapshot?.questionNotebookReferences ??
        questionNotebookReferences;
      const requestSnapshot: MessageRequestSnapshot = replaySnapshot ?? {
        content,
        capability: effectiveCapability,
        enabledTools: [...effectiveTools],
        knowledgeBases: [...effectiveKnowledgeBases],
        language: effectiveLanguage,
        ...(effectiveAttachments?.length
          ? { attachments: effectiveAttachments }
          : {}),
        ...(effectiveConfig && Object.keys(effectiveConfig).length > 0
          ? { config: effectiveConfig }
          : {}),
        ...(effectiveNotebookReferences?.length
          ? { notebookReferences: effectiveNotebookReferences }
          : {}),
        ...(effectiveHistoryReferences?.length
          ? { historyReferences: [...effectiveHistoryReferences] }
          : {}),
        ...(effectiveQuestionNotebookReferences?.length
          ? {
              questionNotebookReferences: [
                ...effectiveQuestionNotebookReferences,
              ],
            }
          : {}),
        ...(effectiveBookReferences?.length
          ? { bookReferences: effectiveBookReferences }
          : {}),
        ...(effectivePersona ? { persona: effectivePersona } : {}),
        ...(effectiveMemoryReferences?.length
          ? { memoryReferences: [...effectiveMemoryReferences] }
          : {}),
        ...(effectiveLLMSelection
          ? { llmSelection: effectiveLLMSelection }
          : {}),
      };
      // Default the new message's parent to the tip of the currently-
      // visible path so the local chat tree stays connected during
      // streaming. The wire-level ``parent_message_id`` is computed
      // separately further down: only persisted (positive) ids or an
      // explicit ``null`` (root edit) are sent — optimistic negative ids
      // would be meaningless to the server.
      const visible = buildVisiblePath(
        session.messages,
        session.selectedBranches,
      ).messages;
      const tipId = tipMessageId(visible);
      const localParentId =
        options?.parentMessageId !== undefined
          ? options.parentMessageId
          : tipId;
      const wireParentId: number | null | undefined =
        options?.parentMessageId !== undefined
          ? options.parentMessageId
          : tipId !== null && tipId > 0
            ? tipId
            : undefined;
      if (options?.displayUserMessage !== false) {
        dispatch({
          type: "ADD_USER_MSG",
          key,
          content,
          capability: effectiveCapability,
          attachments: effectiveAttachments,
          requestSnapshot,
          parentMessageId: localParentId,
        });
      }
      dispatch({ type: "STREAM_START", key });
      const effectiveTurnConfig =
        options?.persistUserMessage === false
          ? { ...(effectiveConfig || {}), _persist_user_message: false }
          : effectiveConfig;
      sendThroughRunner(key, {
        type: "start_turn",
        content,
        tools: effectiveTools,
        capability: effectiveCapability,
        knowledge_bases: effectiveKnowledgeBases,
        session_id: session.sessionId,
        attachments: effectiveAttachments,
        language: effectiveLanguage,
        ...(effectiveNotebookReferences?.length
          ? { notebook_references: effectiveNotebookReferences }
          : {}),
        ...(effectiveHistoryReferences?.length
          ? { history_references: effectiveHistoryReferences }
          : {}),
        ...(effectiveQuestionNotebookReferences?.length
          ? {
              question_notebook_references: effectiveQuestionNotebookReferences,
            }
          : {}),
        ...(effectiveBookReferences?.length
          ? { book_references: effectiveBookReferences }
          : {}),
        // Always sent (possibly ""): an explicit key is the backend's signal
        // to persist the value into session.preferences — "" clears back to
        // Default. Omitting the key would make the backend fall back to the
        // stored preference, so a clear could never propagate.
        persona: effectivePersona,
        ...(effectiveMemoryReferences?.length
          ? { memory_references: effectiveMemoryReferences }
          : {}),
        ...(effectiveLLMSelection
          ? { llm_selection: effectiveLLMSelection }
          : {}),
        ...(effectiveTurnConfig && Object.keys(effectiveTurnConfig).length > 0
          ? { config: effectiveTurnConfig }
          : {}),
        // Send ``parent_message_id`` only when we have a real (positive)
        // server id to chain under, or when the caller explicitly pinned
        // a parent (incl. ``null`` for editing the session's first
        // message). When the visible tip is still an optimistic
        // negative id, omit the key and let the backend auto-append to
        // the latest persisted row.
        ...(wireParentId !== undefined
          ? { parent_message_id: wireParentId }
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
    if (!session) return;
    const turnId = session.activeTurnId;
    const runner = runnersRef.current.get(key);
    if (runner?.client.connected) {
      if (turnId) {
        runner.client.send({ type: "cancel_turn", turn_id: turnId });
      }
      runner.client.disconnect();
      runnersRef.current.delete(key);
    }
    if (session.isStreaming) {
      dispatch({ type: "STREAM_END", key, status: "cancelled" });
    }
  }, []);

  const submitUserReply = useCallback(
    (
      reply:
        | string
        | {
            text?: string;
            answers?: Array<{ questionId: string; text: string }>;
          },
    ) => {
      const currentState = stateRef.current;
      const key = currentState.selectedKey;
      if (!key) return;
      const session = currentState.sessions[key];
      const turnId = session?.activeTurnId;
      const pendingAskUser = session
        ? hasPendingAskUserInMessages(session.messages, turnId)
        : false;
      // Only meaningful while a turn is live. A paused ask_user turn can be
      // silent long enough for the socket to reconnect, so allow submission
      // whenever the unresolved card and active turn id are still present.
      if (!session || !turnId || (!session.isStreaming && !pendingAskUser)) {
        return;
      }
      const message: import("@/lib/unified-ws").SubmitUserReplyMessage = {
        type: "submit_user_reply",
        turn_id: turnId,
      };
      if (typeof reply === "string") {
        message.text = reply;
      } else {
        if (typeof reply.text === "string") message.text = reply.text;
        if (Array.isArray(reply.answers)) message.answers = reply.answers;
      }
      sendThroughRunner(key, message);
    },
    [sendThroughRunner],
  );

  const regenerateLastMessage = useCallback(() => {
    const currentState = stateRef.current;
    const key = currentState.selectedKey;
    if (!key) return;
    const session = currentState.sessions[key];
    if (!session || !session.sessionId) return;
    if (session.isStreaming) return;
    const lastUser = [...session.messages]
      .reverse()
      .find((m) => m.role === "user");
    if (!lastUser) return;
    // Snapshot the trailing assistant (if any) so we can put it back when the
    // server rejects the request. We intentionally keep events/attachments so
    // the restored bubble round-trips identically.
    const lastMessage = session.messages[session.messages.length - 1];
    if (lastMessage && lastMessage.role === "assistant") {
      pendingRegenerateRef.current.set(key, { ...lastMessage });
    } else {
      pendingRegenerateRef.current.delete(key);
    }
    dispatch({ type: "POP_LAST_ASSISTANT", key });
    dispatch({ type: "STREAM_START", key });
    sendThroughRunner(key, {
      type: "regenerate",
      session_id: session.sessionId,
      overrides: {
        language: readStoredLanguage(),
      },
    });
  }, [sendThroughRunner]);

  const derivedState = useMemo<ChatState>(() => {
    const current = ensureSelectedSession(state);
    return {
      sessionId: current.sessionId,
      sessionTitle: current.sessionTitle,
      enabledTools: current.enabledTools,
      activeCapability: current.activeCapability,
      knowledgeBases: current.knowledgeBases,
      llmSelection: current.llmSelection,
      personaSelection: current.personaSelection,
      messages: current.messages,
      isStreaming: current.isStreaming,
      currentStage: current.currentStage,
      language: current.language,
      selectedBranches: current.selectedBranches,
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

  const setLLMSelection = useCallback((selection: LLMSelection | null) => {
    dispatch({ type: "SET_LLM_SELECTION", selection });
  }, []);

  const setPersonaSelection = useCallback((persona: string) => {
    dispatch({ type: "SET_PERSONA_SELECTION", persona });
  }, []);

  const setLanguage = useCallback((lang: string) => {
    dispatch({ type: "SET_LANGUAGE", lang });
  }, []);

  const renameSessionTitle = useCallback(async (title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    const currentState = stateRef.current;
    const key = currentState.selectedKey;
    if (!key) return;
    const session = currentState.sessions[key];
    const sessionId = session?.sessionId;
    if (!sessionId) return;
    const updated = await updateSessionTitle(sessionId, trimmed);
    dispatch({
      type: "SET_SESSION_TITLE",
      key,
      title: updated.title || trimmed,
    });
  }, []);

  const newSession = useCallback(() => {
    dispatch({ type: "NEW_SESSION", key: makeDraftKey() });
  }, [makeDraftKey]);

  const editMessage = useCallback(
    async (messageId: number, newContent: string) => {
      const trimmed = newContent.trim();
      if (!trimmed) return;
      const currentState = stateRef.current;
      const key = currentState.selectedKey;
      if (!key) return;
      const session = currentState.sessions[key];
      if (!session) return;
      // Edits create a new branch via a fresh turn — block while one is
      // already running so we don't queue against an in-flight stream
      // (matches the delete-turn guard).
      if (session.isStreaming) return;
      const idx = session.messages.findIndex(
        (m) => m.id === messageId && m.role === "user",
      );
      if (idx === -1) return;
      let original = session.messages[idx];
      // Optimistic in-flight rows have a negative client-side id — we
      // need a real server id to hang the new sibling under. Refresh
      // from the server, then re-resolve the row by its position in the
      // (now-persisted) thread before continuing.
      if (typeof original.id === "number" && original.id < 0) {
        if (!session.sessionId) return;
        try {
          await loadSession(session.sessionId);
        } catch {
          return;
        }
        const refreshed = stateRef.current.sessions[key];
        const candidate = refreshed?.messages[idx];
        if (
          !candidate ||
          candidate.role !== "user" ||
          typeof candidate.id !== "number" ||
          candidate.id < 0
        ) {
          return;
        }
        original = candidate;
      }
      if (typeof original.id !== "number" || original.id < 0) return;
      const parentId = original.parentMessageId ?? null;
      sendMessage(
        trimmed,
        undefined,
        undefined,
        undefined,
        undefined,
        { parentMessageId: parentId },
        undefined,
        undefined,
        undefined,
      );
    },
    [loadSession, sendMessage],
  );

  const switchBranch = useCallback(
    (parentMessageId: number | null, childId: number) => {
      const currentState = stateRef.current;
      const key = currentState.selectedKey;
      if (!key) return;
      const session = currentState.sessions[key];
      if (!session) return;
      const parentKey =
        parentMessageId == null ? "null" : String(parentMessageId);
      dispatch({
        type: "SET_SELECTED_BRANCH",
        key,
        parentKey,
        childId,
      });
      const sessionId = session.sessionId;
      if (!sessionId) return;
      const nextSelections = {
        ...session.selectedBranches,
        [parentKey]: childId,
      };
      // Fire-and-forget — local state is the source of truth for the UI;
      // the server copy only matters for reload-time hydration.
      updateBranchSelection(sessionId, nextSelections).catch((err) => {
        console.warn("Failed to persist branch selection:", err);
      });
    },
    [],
  );

  const deleteTurn = useCallback(
    async (messageId: number) => {
      const currentState = stateRef.current;
      const key = currentState.selectedKey;
      if (!key) return;
      const session = currentState.sessions[key];
      if (!session || !session.sessionId) return;
      if (session.isStreaming) return;
      let effectiveId = messageId;
      if (messageId < 0) {
        const origIdx = session.messages.findIndex((m) => m.id === messageId);
        if (origIdx === -1) return;
        try {
          await loadSession(session.sessionId);
        } catch {
          return;
        }
        const refreshed = stateRef.current.sessions[key];
        const realId = refreshed?.messages[origIdx]?.id;
        if (realId == null || realId < 0) return;
        effectiveId = realId;
      }
      try {
        await deleteMessage(session.sessionId, effectiveId);
        dispatch({ type: "DELETE_TURN", key, messageId: effectiveId });
      } catch (err) {
        console.error("Failed to delete turn:", err);
      }
    },
    [loadSession],
  );

  // Memoize the context value so consumers don't re-render on every render of
  // this provider. Without this wrap, every stream-event-driven reducer
  // dispatch produced a fresh object identity, cascading a re-render through
  // every `useUnifiedChat()` consumer (chat page, composer, sidebar) on each
  // token. The callbacks below are already stable via useCallback; the only
  // things that should change identity are derivedState, sessionStatuses,
  // and sidebarRefreshToken.
  const value = useMemo<ChatContextValue>(
    () => ({
      state: derivedState,
      setTools,
      setCapability,
      setKBs,
      setLLMSelection,
      setPersonaSelection,
      setLanguage,
      sendMessage,
      cancelStreamingTurn,
      submitUserReply,
      regenerateLastMessage,
      deleteTurn,
      editMessage,
      switchBranch,
      renameSessionTitle,
      newSession,
      loadSession,
      selectedSessionId: derivedState.sessionId,
      sessionStatuses,
      sidebarRefreshToken: state.sidebarRefreshToken,
    }),
    [
      derivedState,
      setTools,
      setCapability,
      setKBs,
      setLLMSelection,
      setPersonaSelection,
      setLanguage,
      sendMessage,
      cancelStreamingTurn,
      submitUserReply,
      regenerateLastMessage,
      deleteTurn,
      editMessage,
      switchBranch,
      renameSessionTitle,
      newSession,
      loadSession,
      sessionStatuses,
      state.sidebarRefreshToken,
    ],
  );

  return <ChatCtx.Provider value={value}>{children}</ChatCtx.Provider>;
}

export function useUnifiedChat() {
  const ctx = useContext(ChatCtx);
  if (!ctx)
    throw new Error("useUnifiedChat must be inside UnifiedChatProvider");
  return ctx;
}
