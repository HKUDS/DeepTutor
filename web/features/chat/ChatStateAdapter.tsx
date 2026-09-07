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
import type { ClientCommand } from "@/contracts/generated/turn-protocol";
import {
  RESPONSE_LANGUAGE_EVENT,
  RESPONSE_LANGUAGE_STORAGE_KEY,
  normalizeLanguage,
  readStoredChatResponseTimeout,
  readStoredResponseLanguage,
  writeStoredActiveSessionId,
} from "@/context/app-shell-storage";
import type {
  StreamEvent,
  ChatMessage,
  LLMSelection,
} from "@/features/chat/model/protocol";
import { UnifiedTurnClient } from "@/features/chat/transport/UnifiedTurnClient";
import { buildStartTurnInput } from "@/features/chat/controllers/buildStartTurnInput";
import {
  getSession,
  getMessageTrace,
  deleteMessage,
  updateBranchSelection,
  updateSessionTitle,
  type MessageTracePage,
  type SessionMessage,
} from "@/lib/session-api";
import {
  TraceCache,
  compactTracePreview,
  settleMessageTrace,
  type MessageTraceMetadata,
} from "@/features/chat/trace/memory";
import {
  appendWithEmphasisRepair,
  normalizeMarkdownForDisplay,
  repairChineseEmphasis,
} from "@/lib/markdown-display";
import { normalizeMessageContent } from "@/lib/message-content";
import {
  buildVisiblePath,
  persistedBranchSelections,
  selectChildBranch,
  tipMessageId,
} from "@/lib/message-branches";
import { nextOptimisticId, resolvePersistedMessage } from "@/lib/optimistic-id";
import { reconcileTurnIds } from "@/lib/turn-reconcile";
import {
  isNarrationMarker,
  recomputeAnswerContent,
  shouldAppendEventContent,
} from "@/lib/stream";
import { hasPendingAskUserInMessages } from "@/lib/ask-user-state";
import { notify } from "@/lib/notifications";
import { forwardReaderAction } from "@/lib/reading-reader-action";
import {
  normalizeReadingMaterialId,
  normalizeReadingMaterialRevision,
  readingTurnFields,
} from "@/lib/reading-turn-state";
import { watchingTurnFields } from "@/lib/watching-turn-state";
import {
  decideIdleTurnRecovery,
  resolveLoadedRunStatus,
} from "@/lib/chat-idle-recovery";
import i18n from "i18next";
import {
  normalizeBookReferences,
  type BookReferencePayload,
} from "@/lib/book-references";
import {
  normalizeWorkspaceMode,
  type WorkspaceMode,
} from "@/lib/workspace-mode";
import {
  normalizeReadingReferences,
  type ReadingReferencePayload,
} from "@/lib/reading-references";

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
  readingReferences?: ReadingReferencePayload[];
  /** Edit-branching: when set, the new user message is inserted as a
   *  sibling under this parent rather than appended to the session tail.
   *  ``null`` means "explicitly attach to the session root". */
  parentMessageId?: number | null;
  /** Which mastery question this message is answering. Set when the message
   *  came from a question card, so the backend can commit the answer to the
   *  engine before the tutor's first token instead of pairing a bare "C"
   *  with a question from scrollback. */
  masteryAnswer?: { question_id: string; text: string } | null;
  /** Which mastery question this message drops. Set when the learner used the
   *  card's skip control, so the engine is clear of it before the tutor's
   *  first ``mastery_status`` — otherwise the next ``mastery_quiz`` simply
   *  re-presents the question they just declined. */
  masterySkip?: { question_id: string } | null;
}

export interface ChatState {
  sessionId: string | null;
  sessionTitle: string;
  enabledTools: string[];
  activeCapability: string | null;
  /** Stable product surface; per-turn capability selection is orthogonal. */
  workspaceMode: WorkspaceMode | null;
  knowledgeBases: string[];
  llmSelection: LLMSelection | null;
  /** Persistent mastery state associated with this conversation. */
  masteryPathId: string | null;
  /** What this mastery conversation is for — "outline" | "study" | "review".
   *  Durable like the path id and decided when the conversation is opened: it
   *  picks the tutor's prompt block and narrows its tool surface, so a session
   *  that changed it mid-way would hand itself tools its kind withholds. */
  masterySessionMode: string | null;
  /** Study course this conversation belongs to; "" = unclassified.
   *  Read by the composer's course pill and sent with every turn, so Course
   *  Study senses the same course the learner can see it is bound to. */
  courseId: string;
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

export interface SessionConfiguration {
  capability?: string | null;
  workspaceMode?: WorkspaceMode | null;
  knowledgeBases?: string[];
  masteryPathId?: string | null;
  masterySessionMode?: string | null;
  courseId?: string;
  enabledTools?: string[];
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
  /** Stable per-attachment id; matches the URL segment served by /files/attachments. */
  id?: string;
  /** Plain-text rendering of office docs, populated by the backend extractor.
   *  Used by the preview drawer to show "what the LLM saw" for binary docs. */
  extracted_text?: string;
  /** Set on files the assistant produced this turn (exec
   *  artifacts) rather than files the user uploaded. Rendered as openable
   *  cards under the assistant message. */
  generated?: boolean;
  /** Byte size of the generated file, for the card's subtitle. */
  size_bytes?: number;
  /** Unified content-workspace presentation metadata. Physical paths are
   * deliberately never sent to the browser. */
  origin?: "workspace";
  workspace_id?: string;
  workspace_item_id?: string;
  relative_path?: string;
  sha256?: string;
  title?: string;
  caption?: string;
}

export interface MessageRequestSnapshot {
  content: string;
  capability?: string | null;
  workspaceMode?: WorkspaceMode | null;
  enabledTools: string[];
  knowledgeBases: string[];
  language: string;
  attachments?: MessageAttachment[];
  config?: Record<string, unknown>;
  notebookReferences?: NotebookReferencePayload[];
  historyReferences?: HistoryReferencePayload;
  questionNotebookReferences?: QuestionNotebookReferencePayload;
  bookReferences?: BookReferencePayload[];
  readingReferences?: ReadingReferencePayload[];
  masteryPathId?: string;
  masterySessionMode?: string;
  timedMediaId?: string;
  persona?: string;
  memoryReferences?: MemoryReferencePayload;
  llmSelection?: LLMSelection | null;
  /** Stable identity of the material open for this turn. */
  readingMaterialId?: string;
  /** Immutable content revision open when the turn was submitted. */
  readingMaterialRevision?: number;
}

export interface MessageItem {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  /** Original model text accumulated during a live stream. Kept separate from
   * `content`, which may be Markdown-normalized for display. */
  rawContent?: string;
  capability?: string;
  events?: StreamEvent[];
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
  trace?: MessageTraceMetadata;
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

/** A session as the server describes it. ``LOAD_SESSION`` applies it and
 *  selects the session; ``REVALIDATE_SESSION`` applies it in the background
 *  to a session the user is already reading. */
interface SessionSnapshot {
  key: string;
  sessionId: string;
  title?: string;
  messages: MessageItem[];
  activeTurnId?: string | null;
  status?: SessionRuntimeStatus;
  tools?: string[];
  capability?: string | null;
  workspaceMode?: WorkspaceMode | null;
  knowledgeBases?: string[];
  llmSelection?: LLMSelection | null;
  masteryPathId?: string | null;
  masterySessionMode?: string | null;
  courseId?: string;
  personaSelection?: string;
  language?: string;
  selectedBranches?: Record<string, number>;
}

type Action =
  | { type: "SET_TOOLS"; tools: string[] }
  | { type: "SET_CAPABILITY"; cap: string | null }
  | { type: "SET_KB"; kbs: string[] }
  | { type: "SET_LLM_SELECTION"; selection: LLMSelection | null }
  // ``key`` targets a specific conversation — a backend push belongs to the
  // session that produced it, which may no longer be the selected one. The
  // composer omits it and means "the one on screen".
  | { type: "SET_MASTERY_PATH_ID"; masteryPathId: string | null; key?: string }
  | { type: "SET_MASTERY_SESSION_MODE"; mode: string | null; key?: string }
  | { type: "SET_COURSE_ID"; courseId: string }
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
  | { type: "STREAM_TOUCH"; key: string }
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
  | ({ type: "LOAD_SESSION" } & SessionSnapshot)
  | ({ type: "REVALIDATE_SESSION" } & SessionSnapshot)
  | { type: "SELECT_SESSION"; key: string }
  | { type: "SET_SESSION_TITLE"; key: string; title: string }
  | {
      type: "RECONCILE_TURN";
      key: string;
      turnId?: string | null;
      userMessageId?: number | null;
      assistantMessageId?: number | null;
    }
  | {
      type: "SET_MESSAGE_TRACE";
      key: string;
      messageId: number;
      events: StreamEvent[];
      trace: MessageTraceMetadata;
    }
  | {
      type: "SETTLE_MESSAGE_TRACE";
      key: string;
      messageId: number;
      turnId: string | null;
    }
  | { type: "DELETE_TURN"; key: string; messageId: number }
  | {
      type: "NEW_SESSION";
      key: string;
      configuration?: SessionConfiguration;
    }
  | {
      type: "CONFIGURE_SESSION";
      key?: string;
      configuration: SessionConfiguration;
    }
  | { type: "ENSURE_DRAFT_SESSION"; key: string }
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
    workspaceMode: null,
    knowledgeBases: [],
    llmSelection: null,
    masteryPathId: null,
    masterySessionMode: null,
    courseId: "",
    personaSelection: "",
    messages: [],
    isStreaming: false,
    currentStage: "",
    language:
      typeof window === "undefined" ? "en" : readStoredResponseLanguage(),
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

function applySessionConfiguration(
  session: SessionEntry,
  configuration?: SessionConfiguration,
): SessionEntry {
  if (!configuration) return session;
  return {
    ...session,
    activeCapability:
      configuration.capability !== undefined
        ? configuration.capability
        : session.activeCapability,
    workspaceMode:
      configuration.workspaceMode !== undefined
        ? configuration.workspaceMode
        : session.workspaceMode,
    knowledgeBases:
      configuration.knowledgeBases !== undefined
        ? [...configuration.knowledgeBases]
        : session.knowledgeBases,
    masteryPathId:
      configuration.masteryPathId !== undefined
        ? configuration.masteryPathId
        : session.masteryPathId,
    masterySessionMode:
      configuration.masterySessionMode !== undefined
        ? configuration.masterySessionMode
        : session.masterySessionMode,
    courseId:
      configuration.courseId !== undefined
        ? configuration.courseId
        : session.courseId,
    enabledTools:
      configuration.enabledTools !== undefined
        ? [...configuration.enabledTools]
        : session.enabledTools,
    updatedAt: Date.now(),
  };
}

/** Add an empty session under ``key`` and make it the selected one. */
function selectFreshDraft(
  state: ProviderState,
  key: string,
  configuration?: SessionConfiguration,
): ProviderState {
  const MAX_CACHED_SESSIONS = 20;
  const nextSessions = {
    ...state.sessions,
    [key]: applySessionConfiguration(createSessionEntry(key), configuration),
  };
  const keys = Object.keys(nextSessions);
  if (keys.length > MAX_CACHED_SESSIONS) {
    const evictable = keys
      .filter((k) => k !== key && nextSessions[k].status !== "running")
      .sort((a, b) => nextSessions[a].updatedAt - nextSessions[b].updatedAt);
    const toRemove = evictable.slice(0, keys.length - MAX_CACHED_SESSIONS);
    for (const k of toRemove) delete nextSessions[k];
  }
  return { ...state, selectedKey: key, sessions: nextSessions };
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
    case "SET_MASTERY_SESSION_MODE": {
      // ``key`` targets the conversation that produced the change: a backend
      // push belongs to the session it came from, which may no longer be the
      // one on screen. The mode buttons omit it and mean "the one I am in".
      if (!action.key) {
        return updateSelectedSession(state, (session) => ({
          ...session,
          masterySessionMode: action.mode,
        }));
      }
      const target = state.sessions[action.key];
      if (!target) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: { ...target, masterySessionMode: action.mode },
        },
      };
    }
    case "SET_MASTERY_PATH_ID": {
      if (!action.key) {
        return updateSelectedSession(state, (session) => ({
          ...session,
          masteryPathId: action.masteryPathId,
        }));
      }
      const target = state.sessions[action.key];
      if (!target) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: { ...target, masteryPathId: action.masteryPathId },
        },
      };
    }
    case "SET_COURSE_ID":
      return updateSelectedSession(state, (session) => ({
        ...session,
        courseId: action.courseId,
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
      const userId = nextOptimisticId();
      const parentId =
        action.parentMessageId === undefined ? null : action.parentMessageId;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: [
              ...session.messages,
              {
                id: userId,
                role: "user",
                content: action.content,
                capability: action.capability || "",
                parentMessageId: parentId,
                ...(action.attachments?.length
                  ? { attachments: action.attachments }
                  : {}),
                ...(action.requestSnapshot
                  ? { requestSnapshot: action.requestSnapshot }
                  : {}),
              },
            ],
            selectedBranches: selectChildBranch(
              session.selectedBranches,
              parentId,
              userId,
            ),
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
                id: nextOptimisticId(),
                role: "assistant",
                content: "",
                rawContent: "",
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
    case "STREAM_TOUCH": {
      const session = state.sessions[action.key];
      if (!session) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: { ...session, updatedAt: Date.now() },
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
          id: nextOptimisticId(),
          role: "assistant",
          content: "",
          rawContent: "",
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
      const language = session.language;
      let rawContent = last?.rawContent ?? last?.content ?? "";
      let content = last?.content ?? "";
      if (isNarrationMarker(action.event)) {
        // A round just resolved as narration (preamble before a tool call):
        // drop its already-streamed text from the answer — it stays in the
        // trace. Recompute from immutable event content, never from display text.
        rawContent = recomputeAnswerContent(events);
        content = repairChineseEmphasis(rawContent, language);
      } else if (shouldAppendEventContent(action.event)) {
        const delta = action.event.content;
        rawContent += delta;
        content = appendWithEmphasisRepair(content, delta, rawContent, language);
      }
      // Any other event (progress, tool rows, stage markers) leaves the text
      // alone, so it reuses the display string as-is. Re-deriving it here was
      // running the Chinese emphasis repair over the whole reply for events
      // that could not have changed a character of it.
      const capability = last?.capability || session.activeCapability || "";
      msgs[msgs.length - 1] = {
        ...(last || { role: "assistant", content: "" }),
        content,
        rawContent,
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
    case "STREAM_END": {
      const ending = state.sessions[action.key];
      // Settle the trailing line: during streaming the emphasis repair runs
      // only when a newline completes a line, so the last one is still raw.
      const settled = (() => {
        if (!ending?.messages?.length) return ending?.messages ?? [];
        const messages = [...ending.messages];
        const last = messages[messages.length - 1];
        if (last?.role !== "assistant") return messages;
        const raw = last.rawContent ?? last.content ?? "";
        const repaired = repairChineseEmphasis(raw, ending.language);
        if (repaired === last.content) return messages;
        messages[messages.length - 1] = { ...last, content: repaired };
        return messages;
      })();
      const endedTurnId = action.turnId || ending?.activeTurnId || null;
      // A completed turn can still own an unanswered card (for example, a
      // replay/sentinel race). Keep its address so submit_user_reply can
      // reach the backend waiter instead of failing the visible card.
      const pendingAskUser =
        action.status === "completed" &&
        hasPendingAskUserInMessages(settled, endedTurnId);
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...(state.sessions[action.key] ?? createSessionEntry(action.key)),
            messages: settled,
            isStreaming: false,
            currentStage: "",
            status: action.status ?? "completed",
            activeTurnId:
              action.status === "running" || pendingAskUser
                ? action.turnId ||
                  state.sessions[action.key]?.activeTurnId ||
                  null
                : null,
            updatedAt: Date.now(),
          },
        },
        sidebarRefreshToken: state.sidebarRefreshToken + 1,
      };
    }
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
    case "SELECT_SESSION": {
      // Show a session we already hold in memory. No fetch, no spinner —
      // the pair to ``REVALIDATE_SESSION``, which refreshes it afterwards.
      if (!state.sessions[action.key]) return state;
      if (state.selectedKey === action.key) return state;
      return { ...state, selectedKey: action.key };
    }
    case "LOAD_SESSION":
    case "REVALIDATE_SESSION": {
      if (action.type === "REVALIDATE_SESSION") {
        // Second line of defence: ``loadSession`` already drops a revalidate
        // whose session went live, but the check belongs here too so no
        // background snapshot can ever clobber a streaming turn.
        const local = state.sessions[action.key];
        if (!local || local.isStreaming || local.status === "running") {
          return state;
        }
      }
      const existing =
        state.sessions[action.key] ??
        createSessionEntry(action.key, action.sessionId);
      return {
        ...state,
        selectedKey:
          action.type === "LOAD_SESSION" ? action.key : state.selectedKey,
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
            workspaceMode:
              action.workspaceMode !== undefined
                ? action.workspaceMode
                : existing.workspaceMode,
            knowledgeBases: action.knowledgeBases ?? existing.knowledgeBases,
            llmSelection:
              action.llmSelection !== undefined
                ? action.llmSelection
                : existing.llmSelection,
            masteryPathId:
              action.masteryPathId !== undefined
                ? action.masteryPathId
                : existing.masteryPathId,
            courseId:
              action.courseId !== undefined
                ? action.courseId
                : existing.courseId,
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
    case "RECONCILE_TURN": {
      // Swap the finished turn's optimistic (negative) message ids for the
      // persisted ids carried on the ``done`` event. This replaces the old
      // "refetch the whole session after every turn" reconcile, whose
      // hydrate + normalize + full re-render froze the tab for seconds on
      // long conversations.
      const session = state.sessions[action.key];
      if (!session) return state;
      const result = reconcileTurnIds(
        session.messages,
        session.selectedBranches,
        {
          turnId: action.turnId,
          userMessageId: action.userMessageId,
          assistantMessageId: action.assistantMessageId,
        },
      );
      if (!result.changed) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: {
            ...session,
            messages: result.messages,
            selectedBranches: result.selectedBranches,
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "SET_MESSAGE_TRACE": {
      const session = state.sessions[action.key];
      if (!session) return state;
      const messages = session.messages.map((message) =>
        message.id === action.messageId && message.role === "assistant"
          ? { ...message, events: action.events, trace: action.trace }
          : message,
      );
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: { ...session, messages, updatedAt: Date.now() },
        },
      };
    }
    case "SETTLE_MESSAGE_TRACE": {
      // The finished message trades its full event list for the compact
      // preview it keeps in memory. Done here, from the events the reducer
      // holds, rather than from a snapshot taken in the ``done`` handler: that
      // snapshot lags React's commit, and the last round's content, tool call
      // and card arrive in the same burst as ``done`` — a stale snapshot
      // settled the message on a trace without its card.
      const session = state.sessions[action.key];
      if (!session) return state;
      let changed = false;
      const messages = session.messages.map((message) => {
        if (message.id !== action.messageId || message.role !== "assistant") {
          return message;
        }
        changed = true;
        return {
          ...message,
          ...settleMessageTrace(message.events ?? [], action.turnId),
        };
      });
      if (!changed) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [action.key]: { ...session, messages, updatedAt: Date.now() },
        },
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
    case "NEW_SESSION":
      return selectFreshDraft(state, action.key, action.configuration);
    case "CONFIGURE_SESSION": {
      const key = action.key || state.selectedKey;
      if (!key) return state;
      const session = state.sessions[key];
      if (!session) return state;
      return {
        ...state,
        sessions: {
          ...state.sessions,
          [key]: applySessionConfiguration(session, action.configuration),
        },
      };
    }
    // Idempotent variant of NEW_SESSION: guarantees there is *a* selected
    // session without discarding one a page already selected and configured.
    // The check belongs here rather than in the caller because a mount effect
    // only ever sees the state of the render that created it, which is stale
    // the moment anything else has dispatched.
    case "ENSURE_DRAFT_SESSION":
      if (state.selectedKey && state.sessions[state.selectedKey]) return state;
      return selectFreshDraft(state, action.key);
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

/**
 * How long after DONE to refetch the sidebar so a post-turn title shows up.
 *
 * The title is written *after* the turn finishes (see `title_service`), so the
 * sidebar refresh that `STREAM_END` already triggers necessarily runs before
 * the title exists — it re-reads the list and gets the placeholder that was
 * there all along, which is why a finished conversation could sit on "New
 * conversation" forever.
 *
 * The backend publishes the title as a post-DONE `session_meta` frame and the
 * client holds the socket open for it (above), so that is the primary path —
 * it was broken until the subscription stopped closing itself on DONE
 * (`TurnApplication.subscribe_turn`). This refetch stays as the belt to that
 * brace: a socket dropped between DONE and the title would otherwise lose it
 * with no second chance, and the cost is one list fetch per turn.
 */
const POST_DONE_TITLE_REFRESH_MS = 5_000;

interface ChatContextValue {
  state: ChatState;
  setTools: (tools: string[]) => void;
  setCapability: (cap: string | null) => void;
  setKBs: (kbs: string[]) => void;
  setLLMSelection: (selection: LLMSelection | null) => void;
  setMasteryPathId: (masteryPathId: string | null) => void;
  /** What this mastery conversation is doing — see lib/mastery-mode. */
  setMasterySessionMode: (mode: string | null) => void;
  setCourseId: (courseId: string) => void;
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
   * and resume the agentic loop on the **same** turn.
   *
   * Resolves with whether the reply actually reached a turn that was
   * waiting for it. A question card outlives the turn that asked it — a
   * backend restart drops the waiter while the card stays on screen, fully
   * interactive — so "did this land?" has to be answerable by whoever is
   * showing the card, or the learner is left watching a spinner that will
   * never resolve.
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
  ) => Promise<boolean>;
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
  newSession: (configuration?: SessionConfiguration) => void;
  /** Apply route-owned preferences to an explicit loaded session (or the
   * selected draft). Dispatching by key keeps this safe immediately after
   * LOAD_SESSION, before React has committed a new context render. */
  configureSession: (
    configuration: SessionConfiguration,
    sessionKey?: string,
  ) => void;
  /** Fetch a session and apply it. Pass ``revalidate`` when the session is
   *  already on screen (see ``showCachedSession``): the snapshot is then
   *  dropped rather than applied if a turn started meanwhile. */
  loadSession: (
    sessionId: string,
    options?: { signal?: AbortSignal; revalidate?: boolean },
  ) => Promise<MessageItem[] | undefined>;
  /** Select an already-loaded session without fetching. Returns false when
   *  it isn't in memory, i.e. the caller must load it. */
  showCachedSession: (sessionId: string) => boolean;
  /** Lazily fetch one persisted turn trace and retain its compact preview. */
  loadMessageTrace: (sessionId: string, messageId: number) => Promise<void>;
  /** Restore the compact preview when a full trace is collapsed. */
  releaseMessageTrace: (sessionId: string, messageId: number) => void;
  selectedSessionId: string | null;
  sessionStatuses: Record<string, SessionStatusSnapshot>;
  sidebarRefreshToken: number;
}

const ChatCtx = createContext<ChatContextValue | null>(null);

export function hydrateMessageAttachments(
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
        origin: item.origin,
        workspace_id: item.workspace_id,
        workspace_item_id: item.workspace_item_id,
        relative_path: item.relative_path,
        sha256: item.sha256,
        title: item.title,
        caption: item.caption,
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
    workspaceMode: normalizeWorkspaceMode(
      stored.workspaceMode ?? stored.workspace_mode,
      stored.capability ?? message.capability,
    ),
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
  const readingReferences = normalizeReadingReferences(
    stored.readingReferences,
  );
  const llmSelection = asLLMSelection(stored.llmSelection);
  const masteryPathId =
    typeof (stored.masteryPathId ?? stored.mastery_path_id) === "string"
      ? String(stored.masteryPathId ?? stored.mastery_path_id).trim()
      : "";
  const readingMaterialId = normalizeReadingMaterialId(
    stored.readingMaterialId ?? stored.reading_material_id,
  );
  const readingMaterialRevision = normalizeReadingMaterialRevision(
    stored.readingMaterialRevision ?? stored.reading_material_revision,
  );
  const timedMediaId =
    typeof (stored.timedMediaId ?? stored.timed_media_id) === "string"
      ? String(stored.timedMediaId ?? stored.timed_media_id).trim()
      : "";

  if (config && Object.keys(config).length) snapshot.config = config;
  if (notebookReferences.length)
    snapshot.notebookReferences = notebookReferences;
  if (historyReferences.length) snapshot.historyReferences = historyReferences;
  if (questionNotebookReferences.length) {
    snapshot.questionNotebookReferences = questionNotebookReferences;
  }
  if (bookReferences.length) snapshot.bookReferences = bookReferences;
  if (readingReferences.length) {
    snapshot.readingReferences = readingReferences;
  }
  if (persona) snapshot.persona = persona;
  if (memoryReferences.length) snapshot.memoryReferences = memoryReferences;
  if (llmSelection) snapshot.llmSelection = llmSelection;
  if (masteryPathId) snapshot.masteryPathId = masteryPathId;
  if (readingMaterialId) {
    snapshot.readingMaterialId = readingMaterialId;
    if (readingMaterialRevision) {
      snapshot.readingMaterialRevision = readingMaterialRevision;
    }
  }
  if (timedMediaId) snapshot.timedMediaId = timedMediaId;
  return snapshot;
}

export function ChatStateAdapterProvider({
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
        client: UnifiedTurnClient;
      }
    >
  >(new Map());
  const draftCounterRef = useRef(0);
  const retryTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  // Tracks in-flight regenerate requests so we can restore the popped
  // assistant message if the server rejects the request (e.g. ``regenerate_busy``
  // or ``nothing_to_regenerate``). Keyed by session entry key.
  const pendingRegenerateRef = useRef<Map<string, MessageItem>>(new Map());
  const traceCacheRef = useRef<TraceCache>(new TraceCache());
  const traceRequestsRef = useRef<Map<string, AbortController>>(new Map());
  // Forward-declared so ``handleRunnerEvent`` (created above
  // ``loadSession`` in source order) can trigger a server refresh after
  // a turn finishes without taking a stale closure of ``loadSession``.
  const loadSessionRef = useRef<
    ((sessionId: string) => Promise<MessageItem[] | undefined>) | null
  >(null);

  useLayoutEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (!state.selectedKey) return;
    for (const [key, controller] of traceRequestsRef.current) {
      if (key.startsWith(`${state.selectedKey}:`)) continue;
      controller.abort();
      traceRequestsRef.current.delete(key);
    }
    const released = traceCacheRef.current.releaseExcept(state.selectedKey);
    for (const [key, snapshot] of released) {
      const [sessionId, messageId] = key.split(":");
      dispatch({
        type: "SET_MESSAGE_TRACE",
        key: sessionId,
        messageId: Number(messageId),
        events: snapshot.events,
        trace: snapshot.metadata ?? {},
      });
    }
  }, [state.selectedKey]);

  useEffect(
    () => () => {
      runnersRef.current.forEach(({ client }) => client.disconnect());
      runnersRef.current.clear();
      retryTimersRef.current.forEach((id) => clearTimeout(id));
      retryTimersRef.current.clear();
      traceRequestsRef.current.forEach((controller) => controller.abort());
      traceRequestsRef.current.clear();
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
        // A row with no text, no attachments and no events has nothing to
        // render — it comes out as an empty bubble. Worse, it still counts as
        // a message, so a conversation holding only such a row shows neither
        // a transcript nor the surface's own empty state: the reading
        // companion went blank, the chat page lost its opening suggestions.
        // A turn interrupted before its first token leaves exactly this
        // behind. A streaming assistant message is not affected: it is built
        // locally as events arrive, never hydrated from the server.
        .filter(
          (message) =>
            normalizeMessageContent(message.content as unknown).trim() !== "" ||
            (message.attachments?.length ?? 0) > 0 ||
            (Array.isArray(message.events) && message.events.length > 0),
        )
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
            trace: message.trace,
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
      // Reading tools ask the reader to act (scroll to a locator, show a mark
      // they just made) by tagging their result metadata. Re-broadcast it as a
      // DOM event so the reader pane can listen without the chat knowing it
      // exists — the same pattern the visualize prompt bridge uses.
      forwardReaderAction(event);
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
        // Post-turn metadata push: session state the backend settled during
        // the turn. It writes each value to its store *before* sending this,
        // so applying it here only catches the open client up to what a
        // reload would already show.
        const meta = event.metadata as
          | {
              title?: string;
              mastery_path_id?: string;
              mastery_session_mode?: string;
            }
          | undefined;
        // The tutor can move a conversation between mastery paths mid-turn;
        // without this the composer would keep naming the path it started on.
        if (typeof meta?.mastery_path_id === "string") {
          dispatch({
            type: "SET_MASTERY_PATH_ID",
            key: effectiveKey,
            masteryPathId: meta.mastery_path_id.trim() || null,
          });
        }
        // …and it can change what the conversation is doing. The three mode
        // buttons above the transcript are the learner's only sign of which
        // tools the tutor may reach for, so a switch the tutor made itself has
        // to move them: "I've switched to outline mode" over a header still
        // reading "Study" is the product contradicting itself out loud.
        if (typeof meta?.mastery_session_mode === "string") {
          dispatch({
            type: "SET_MASTERY_SESSION_MODE",
            key: effectiveKey,
            mode: meta.mastery_session_mode.trim() || null,
          });
        }
        const title = String(meta?.title || "").trim();
        if (title) {
          dispatch({
            type: "SET_SESSION_TITLE",
            key: effectiveKey,
            title,
          });
        } else if (!meta?.mastery_path_id) {
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
        // Pick up a title written after this point — see
        // POST_DONE_TITLE_REFRESH_MS.
        window.setTimeout(() => {
          dispatch({ type: "BUMP_SIDEBAR_REFRESH" });
        }, POST_DONE_TITLE_REFRESH_MS);
        // Reconcile optimistic client-side message ids with the
        // server's real ids after the turn finishes. Without this the
        // Edit button (which needs a real id to attach the new branch
        // under) and branch navigation (which keys off real ids) would
        // stay disabled until the user navigates away and back. The
        // backend attaches the persisted ids to the ``done`` event, so
        // this is an in-place swap — refetching the whole session here
        // (the previous approach) re-downloaded, re-normalized, and
        // re-rendered the entire transcript after every turn, freezing
        // the tab for seconds on long conversations.
        if (status === "completed") {
          const doneMeta = event.metadata as {
            user_message_id?: number;
            assistant_message_id?: number;
          } | null;
          const assistantMessageId = doneMeta?.assistant_message_id ?? null;
          if (assistantMessageId != null) {
            dispatch({
              type: "RECONCILE_TURN",
              key: effectiveKey,
              turnId: event.turn_id || null,
              userMessageId: doneMeta?.user_message_id ?? null,
              assistantMessageId,
            });
            // Compact the finished message's trace inside the reducer — never
            // from ``stateRef``, which still lacks whatever arrived in the
            // same burst as this ``done``.
            dispatch({
              type: "SETTLE_MESSAGE_TRACE",
              key: effectiveKey,
              messageId: assistantMessageId,
              turnId: event.turn_id || null,
            });
          } else {
            // Older backend without ids on ``done`` — fall back to the
            // full session refetch.
            const finishedSession = stateRef.current.sessions[effectiveKey];
            const sessionId = finishedSession?.sessionId;
            if (sessionId) {
              loadSessionRef.current?.(sessionId).catch(() => {
                /* non-fatal — local state remains usable */
              });
            }
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
        client: new UnifiedTurnClient(
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
                {
                  tone: "error",
                  durationMs: 6000,
                },
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
    function dispatchToRunner(
      key: string,
      msg: ChatMessage | ClientCommand,
      options: { awaitAck?: boolean; attempt?: number } = {},
    ): Promise<boolean> {
      const attempt = options.attempt ?? 0;
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
            {
              tone: "error",
              durationMs: 6000,
            },
          );
          return Promise.resolve(false);
        }
        return new Promise<boolean>((resolve) => {
          const timerId = setTimeout(() => {
            retryTimersRef.current.delete(timerId);
            resolve(
              dispatchToRunner(key, msg, { ...options, attempt: attempt + 1 }),
            );
          }, 200);
          retryTimersRef.current.add(timerId);
        });
      }
      if (options.awaitAck) {
        return runner.client.sendAwaitingAck(msg as ClientCommand);
      }
      runner.client.send(msg);
      return Promise.resolve(true);
    },
    [ensureRunner],
  );

  /** Select a session we already hold in memory, if we do.
   *
   *  Lets a caller paint a previously-opened conversation immediately and
   *  refresh it in the background (``loadSession`` with ``revalidate``),
   *  rather than blanking the view behind a spinner for a round-trip whose
   *  result it usually already has. */
  const showCachedSession = useCallback((sessionId: string) => {
    const cached = stateRef.current.sessions[sessionId];
    if (!cached?.messages.length) return false;
    dispatch({ type: "SELECT_SESSION", key: sessionId });
    return true;
  }, []);

  const releaseMessageTrace = useCallback((sessionId: string, messageId: number) => {
    const key = `${sessionId}:${messageId}`;
    traceRequestsRef.current.get(key)?.abort();
    traceRequestsRef.current.delete(key);
    const preview = traceCacheRef.current.release(key);
    if (!preview) return;
    dispatch({
      type: "SET_MESSAGE_TRACE",
      key: sessionId,
      messageId,
      events: preview.events,
      trace: preview.metadata ?? {},
    });
  }, []);

  const loadMessageTrace = useCallback(
    async (sessionId: string, messageId: number) => {
      const key = `${sessionId}:${messageId}`;
      if (traceCacheRef.current.has(key) || traceRequestsRef.current.has(key)) return;
      const session = stateRef.current.sessions[sessionId];
      if (!session || session.isStreaming || session.status === "running") return;
      const message = session.messages.find(
        (item) => item.id === messageId && item.role === "assistant",
      );
      if (!message?.trace?.turn_id) return;

      const controller = new AbortController();
      traceRequestsRef.current.set(key, controller);
      try {
        const events: StreamEvent[] = [];
        let afterSeq = 0;
        let page: MessageTracePage | null = null;
        for (let pageCount = 0; pageCount < 1000; pageCount += 1) {
          page = await getMessageTrace(
            sessionId,
            messageId,
            afterSeq,
            controller.signal,
          );
          events.push(...page.events);
          if (page.complete || page.next_seq == null) break;
          if (page.next_seq <= afterSeq) return;
          afterSeq = page.next_seq;
        }
        if (!page || controller.signal.aborted) return;
        const metadata: MessageTraceMetadata = {
          turn_id: page.turn_id,
          total: page.total,
          last_seq: page.last_seq,
          truncated: false,
        };
        const preview = compactTracePreview(message.events ?? []);
        const evicted = traceCacheRef.current.retain(key, {
          events: preview.events,
          metadata: message.trace,
        });
        for (const [evictedKey, snapshot] of evicted) {
          const [evictedSession, evictedMessage] = evictedKey.split(":");
          dispatch({
            type: "SET_MESSAGE_TRACE",
            key: evictedSession,
            messageId: Number(evictedMessage),
            events: snapshot.events,
            trace: snapshot.metadata ?? {},
          });
        }
        dispatch({
          type: "SET_MESSAGE_TRACE",
          key: sessionId,
          messageId,
          events,
          trace: metadata,
        });
      } catch (reason) {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          console.warn("Failed to load message trace", reason);
        }
      } finally {
        if (traceRequestsRef.current.get(key) === controller) {
          traceRequestsRef.current.delete(key);
        }
      }
    },
    [],
  );

  const loadSession = useCallback(
    async (
      sessionId: string,
      options?: { signal?: AbortSignal; revalidate?: boolean },
    ) => {
      const session = await getSession(sessionId, options?.signal);
      const key = session.session_id || session.id;
      const activeTurn = Array.isArray(session.active_turns)
        ? session.active_turns[0]
        : undefined;
      if (options?.revalidate) {
        // Background refresh of a session already on screen. Drop the whole
        // snapshot — data *and* the re-subscribe below — once a turn is live
        // locally: this tab is already receiving that turn's events, so
        // re-subscribing from ``after_seq: 0`` would replay them on top of
        // what we have, and the snapshot predates the turn anyway.
        const local = stateRef.current.sessions[key];
        if (!local || local.isStreaming || local.status === "running") return;
      }
      traceCacheRef.current.clear();
      const messages = hydrateMessages(session.messages ?? []);
      const loadedWorkspaceMode = normalizeWorkspaceMode(
        session.preferences?.workspace_mode,
        session.preferences?.capability,
      );
      // A stored `running` is only believable while it is recent — see
      // `resolveLoadedRunStatus`. A turn the backend never got to close out
      // (crash, restart) would otherwise open the conversation into a
      // permanent "answering" state: Stop instead of Send, with no stream to
      // stop and no way back except starting a new conversation.
      const loadedStatus = resolveLoadedRunStatus(
        (session.status as SessionRuntimeStatus | undefined) ||
          (activeTurn ? "running" : "idle"),
        Number(session.updated_at) > 0 ? Number(session.updated_at) * 1000 : 0,
        Date.now(),
        readStoredChatResponseTimeout() * 1000,
      );
      dispatch({
        type: options?.revalidate ? "REVALIDATE_SESSION" : "LOAD_SESSION",
        key,
        sessionId: key,
        title: session.title || "",
        messages,
        activeTurnId: activeTurn?.turn_id || activeTurn?.id || null,
        status: loadedStatus,
        tools: Array.isArray(session.preferences?.tools)
          ? session.preferences.tools
          : [],
        // Old sessions stored Reading/Mastery as the capability itself. Once
        // promoted to a workspace mode, that value means the default Chat
        // action rather than a hidden legacy entry in the action picker.
        capability:
          session.preferences?.capability === loadedWorkspaceMode
            ? null
            : session.preferences?.capability || null,
        workspaceMode: loadedWorkspaceMode,
        knowledgeBases: Array.isArray(session.preferences?.knowledge_bases)
          ? session.preferences.knowledge_bases
          : [],
        llmSelection: asLLMSelection(session.preferences?.llm_selection),
        masteryPathId:
          typeof session.preferences?.mastery_path_id === "string"
            ? session.preferences.mastery_path_id
            : null,
        masterySessionMode:
          typeof session.preferences?.mastery_session_mode === "string"
            ? session.preferences.mastery_session_mode
            : null,
        // The server is the truth for which course a conversation belongs to:
        // it is set from the launch URL, from the composer's pill, and from the
        // sidebar's "move to course", and every one of those writes here.
        courseId:
          typeof session.preferences?.course_id === "string"
            ? session.preferences.course_id
            : "",
        personaSelection:
          typeof session.preferences?.persona === "string"
            ? session.preferences.persona
            : "",
        // Model output language is account-level state. Historical sessions
        // may have stale persisted preferences, so new turns follow the
        // current response-language setting rather than their original value.
        language: readStoredResponseLanguage(),
        selectedBranches: normalizeSelectedBranches(
          session.preferences?.selected_branches,
        ),
      });
      if (loadedStatus === "running" && (activeTurn?.turn_id || activeTurn?.id)) {
        // Reached on a revalidate too, when the turn is live on the server but
        // not in this tab (started in another tab, or our socket dropped) —
        // that is exactly the case that still needs a subscribe. A turn we
        // just judged stale is not one of them: subscribing would open a
        // socket for a turn that will never speak again.
        sendThroughRunner(key, {
          type: "subscribe_turn",
          turn_id: activeTurn.turn_id || activeTurn.id,
          after_seq: 0,
        });
      }
      return messages;
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
    const onResponseLanguage = (event: Event) => {
      const detail = (event as CustomEvent<{ language?: string }>).detail;
      syncLanguage(detail?.language);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === RESPONSE_LANGUAGE_STORAGE_KEY)
        syncLanguage(event.newValue);
    };

    window.addEventListener(RESPONSE_LANGUAGE_EVENT, onResponseLanguage);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(RESPONSE_LANGUAGE_EVENT, onResponseLanguage);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  // URL is now the source of truth for session loading.
  // Chat pages load sessions based on URL params; no sessionStorage restore needed.
  // Initialize a draft session so the provider always has a selected key.
  //
  // React flushes a child's effects before its parent's, so any page under
  // this provider has already picked and configured its session by the time
  // this runs — a plain NEW_SESSION here would throw that away (it is what
  // used to silently drop ``/chat?capability=…&mastery_path_id=…``). The
  // reducer decides on live state; this only supplies the key it may need.
  useEffect(() => {
    if (typeof window === "undefined") return;
    dispatch({ type: "ENSURE_DRAFT_SESSION", key: makeDraftKey() });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Idle recovery: if a streaming session receives no events for the
  // configured window (default 180s, set in Settings > Network), re-subscribe
  // from the last sequence. A quiet stream is not terminal: long research
  // calls can emit nothing for minutes, while a dropped browser connection
  // leaves the backend turn alive with replayable events.
  useEffect(() => {
    const CHECK_INTERVAL_MS = 10_000;

    const timer = setInterval(() => {
      const timeoutSeconds = readStoredChatResponseTimeout();
      const idleTimeoutMs = timeoutSeconds * 1000;
      const current = stateRef.current;
      for (const [key, session] of Object.entries(current.sessions)) {
        const decision = decideIdleTurnRecovery({
          isStreaming: session.isStreaming,
          hasPendingUserInput: hasPendingAskUserInMessages(
            session.messages,
            session.activeTurnId,
          ),
          activeTurnId: session.activeTurnId,
          lastSeq: session.lastSeq,
          updatedAt: session.updatedAt,
          now: Date.now(),
          idleTimeoutMs,
        });
        if (decision.kind === "none") continue;

        if (decision.kind === "resubscribe") {
          // Avoid retrying on every watchdog tick while the re-subscription is
          // opening. The next event will replace this timestamp naturally.
          dispatch({ type: "STREAM_TOUCH", key });
          sendThroughRunner(key, decision.message);
          continue;
        }

        // A local timeout cannot invent a terminal state. Mark the session as
        // observed so the runtime/session reconciliation path can query the
        // authoritative turn once the server supplies its id.
        dispatch({ type: "STREAM_TOUCH", key });
      }
    }, CHECK_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [sendThroughRunner]);

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
      const effectiveWorkspaceMode =
        replaySnapshot?.workspaceMode ?? session.workspaceMode;
      const effectiveTools =
        replaySnapshot?.enabledTools ?? session.enabledTools;
      const effectiveKnowledgeBases =
        replaySnapshot?.knowledgeBases ?? session.knowledgeBases;
      const effectiveLLMSelection =
        replaySnapshot && "llmSelection" in replaySnapshot
          ? (replaySnapshot.llmSelection ?? null)
          : session.llmSelection;
      const effectiveMasteryPathId =
        replaySnapshot?.masteryPathId ?? session.masteryPathId;
      const effectiveMasterySessionMode =
        replaySnapshot?.masterySessionMode ?? session.masterySessionMode;
      const effectiveLanguage =
        replaySnapshot?.language ?? readStoredResponseLanguage();
      // Persona resolution: replay snapshot wins; then an explicit per-call
      // persona (quiz follow-up surface); then the session-level preference.
      // Always a string — "" means Default / no persona.
      const effectivePersona =
        replaySnapshot?.persona ?? persona ?? session.personaSelection ?? "";
      const effectiveMemoryReferences =
        replaySnapshot?.memoryReferences ?? memoryReferences;
      const effectiveBookReferences =
        replaySnapshot?.bookReferences ?? options?.bookReferences;
      const effectiveReadingReferences =
        replaySnapshot?.readingReferences ?? options?.readingReferences;
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
      const liveReadingFields = readingTurnFields(effectiveWorkspaceMode);
      const effectiveReadingTurnFields = replaySnapshot?.readingMaterialId
        ? {
            reading_material_id: replaySnapshot.readingMaterialId,
            ...(replaySnapshot.readingMaterialRevision
              ? {
                  reading_material_revision:
                    replaySnapshot.readingMaterialRevision,
                }
              : {}),
          }
        : liveReadingFields;
      const effectiveReadingMaterialId =
        effectiveReadingTurnFields.reading_material_id;
      const effectiveReadingMaterialRevision =
        effectiveReadingTurnFields.reading_material_revision;
      const liveWatchingFields = watchingTurnFields(effectiveCapability);
      const effectiveWatchingTurnFields = replaySnapshot?.timedMediaId
        ? { timed_media_id: replaySnapshot.timedMediaId }
        : liveWatchingFields;
      const effectiveTimedMediaId =
        effectiveWatchingTurnFields.timed_media_id;
      const requestSnapshot: MessageRequestSnapshot = replaySnapshot ?? {
        content,
        capability: effectiveCapability,
        workspaceMode: effectiveWorkspaceMode,
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
        ...(effectiveReadingReferences?.length
          ? { readingReferences: effectiveReadingReferences }
          : {}),
        ...(effectiveMasteryPathId
          ? { masteryPathId: effectiveMasteryPathId }
          : {}),
        ...(effectiveMasterySessionMode
          ? { masterySessionMode: effectiveMasterySessionMode }
          : {}),
        ...(effectivePersona ? { persona: effectivePersona } : {}),
        ...(effectiveMemoryReferences?.length
          ? { memoryReferences: [...effectiveMemoryReferences] }
          : {}),
        ...(effectiveLLMSelection
          ? { llmSelection: effectiveLLMSelection }
          : {}),
        ...(effectiveReadingMaterialId
          ? { readingMaterialId: effectiveReadingMaterialId }
          : {}),
        ...(effectiveReadingMaterialId && effectiveReadingMaterialRevision
          ? { readingMaterialRevision: effectiveReadingMaterialRevision }
          : {}),
        ...(effectiveTimedMediaId
          ? { timedMediaId: effectiveTimedMediaId }
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
      const {
        _persist_user_message: legacyPersistUserMessage,
        _course_id: _legacyCourseId,
        followup_question_context: followupQuestionContext,
        selection_tutor_context: selectionTutorContext,
        subagent_consult_budget: subagentConsultBudget,
        auto_route: autoRoute,
        ...finalTurnConfig
      } = effectiveConfig ?? {};
      const persistUserMessage =
        options?.persistUserMessage === false ||
        legacyPersistUserMessage === false
          ? false
          : undefined;
      sendThroughRunner(
        key,
        buildStartTurnInput({
        content,
        tools: effectiveTools,
        capability: effectiveCapability,
        workspaceMode: effectiveWorkspaceMode ?? "",
        knowledgeBases: effectiveKnowledgeBases,
        sessionId: session.sessionId,
        courseId: session.courseId.trim() || null,
        persistUserMessage,
        followupQuestionContext:
          followupQuestionContext && typeof followupQuestionContext === "object"
            ? (followupQuestionContext as Record<string, unknown>)
            : null,
        selectionTutorContext:
          selectionTutorContext && typeof selectionTutorContext === "object"
            ? (selectionTutorContext as Record<string, unknown>)
            : null,
        subagentConsultBudget:
          typeof subagentConsultBudget === "number"
            ? subagentConsultBudget
            : null,
        autoRoute: typeof autoRoute === "boolean" ? autoRoute : null,
        attachments: effectiveAttachments,
        language: effectiveLanguage,
        notebookReferences: effectiveNotebookReferences,
        historyReferences: effectiveHistoryReferences,
        questionNotebookReferences: effectiveQuestionNotebookReferences,
        bookReferences: effectiveBookReferences,
        readingReferences: effectiveReadingReferences,
        masteryPathId: effectiveMasteryPathId || null,
        masteryAnswer: options?.masteryAnswer ?? null,
        masterySkip: options?.masterySkip ?? null,
        // Immersive reading. Gated on the stable workspace mode as well as on
        // an open document: the reader outlives action switches and new
        // sessions, so Home must never inherit its source context.
        // Read from a module cell rather than context state so scrolling the
        // reader never re-renders the chat.
        readingWorkspaceId:
          effectiveReadingTurnFields.reading_workspace_id ?? null,
        readingMaterialId:
          effectiveReadingTurnFields.reading_material_id ?? null,
        readingMaterialRevision:
          effectiveReadingTurnFields.reading_material_revision ?? null,
        readingViewport: effectiveReadingTurnFields.reading_viewport ?? null,
        timedMediaId: effectiveWatchingTurnFields.timed_media_id ?? null,
        timedMediaViewport:
          effectiveWatchingTurnFields.timed_media_viewport ?? null,
        // Always sent (possibly ""): an explicit key is the backend's signal
        // to persist the value into session.preferences — "" clears back to
        // Default. Omitting the key would make the backend fall back to the
        // stored preference, so a clear could never propagate.
        persona: effectivePersona,
        memoryReferences: effectiveMemoryReferences,
        llmSelection: effectiveLLMSelection,
        capabilityConfig: finalTurnConfig,
        // Send ``parent_message_id`` only when we have a real (positive)
        // server id to chain under, or when the caller explicitly pinned
        // a parent (incl. ``null`` for editing the session's first
        // message). When the visible tip is still an optimistic
        // negative id, omit the key and let the backend auto-append to
        // the latest persisted row.
        parentMessageId: wireParentId,
        }),
      );
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
    async (
      reply:
        | string
        | {
            text?: string;
            answers?: Array<{ questionId: string; text: string }>;
          },
    ): Promise<boolean> => {
      const currentState = stateRef.current;
      const key = currentState.selectedKey;
      if (!key) return false;
      const session = currentState.sessions[key];
      const turnId = session?.activeTurnId;
      const pendingAskUser = session
        ? hasPendingAskUserInMessages(session.messages, turnId)
        : false;
      // Only meaningful while a turn is live. A paused ask_user turn can be
      // silent long enough for the socket to reconnect, so allow submission
      // whenever the unresolved card and active turn id are still present.
      if (!session || !turnId || (!session.isStreaming && !pendingAskUser)) {
        return false;
      }
      const message: import("@/features/chat/model/protocol").SubmitUserReplyMessage =
        {
          type: "submit_user_reply",
          turn_id: turnId,
        };
      if (typeof reply === "string") {
        message.text = reply;
      } else {
        if (typeof reply.text === "string") message.text = reply.text;
        if (Array.isArray(reply.answers)) message.answers = reply.answers;
      }
      return sendThroughRunner(key, message, { awaitAck: true });
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
        language: readStoredResponseLanguage(),
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
      workspaceMode: current.workspaceMode,
      knowledgeBases: current.knowledgeBases,
      llmSelection: current.llmSelection,
      masteryPathId: current.masteryPathId,
      masterySessionMode: current.masterySessionMode,
      courseId: current.courseId,
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

  const setMasteryPathId = useCallback((masteryPathId: string | null) => {
    const normalized = masteryPathId?.trim() || null;
    dispatch({ type: "SET_MASTERY_PATH_ID", masteryPathId: normalized });
  }, []);

  const setMasterySessionMode = useCallback((mode: string | null) => {
    dispatch({
      type: "SET_MASTERY_SESSION_MODE",
      mode: mode?.trim() || null,
    });
  }, []);

  const setCourseId = useCallback((courseId: string) => {
    dispatch({ type: "SET_COURSE_ID", courseId: courseId.trim() });
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

  const newSession = useCallback(
    (configuration?: SessionConfiguration) => {
      dispatch({ type: "NEW_SESSION", key: makeDraftKey(), configuration });
    },
    [makeDraftKey],
  );

  const configureSession = useCallback(
    (configuration: SessionConfiguration, sessionKey?: string) => {
      dispatch({
        type: "CONFIGURE_SESSION",
        key: sessionKey,
        configuration,
      });
    },
    [],
  );

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
      let original: MessageItem | undefined;
      try {
        original = await resolvePersistedMessage(
          session.messages,
          messageId,
          "user",
          async () =>
            session.sessionId
              ? await loadSession(session.sessionId)
              : undefined,
        );
      } catch {
        return;
      }
      if (!original) return;
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
      if (!sessionId || childId < 0) return;
      const nextSelections = persistedBranchSelections({
        ...session.selectedBranches,
        [parentKey]: childId,
      });
      if (Object.keys(nextSelections).length === 0) return;
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
      // Same optimistic-id race as editMessage (#739): after loadSession
      // dispatches, stateRef can still hold the negative sentinel until
      // React commits. Resolve from the returned snapshot instead.
      let target: MessageItem | undefined;
      try {
        target = await resolvePersistedMessage(
          session.messages,
          messageId,
          "user",
          async () =>
            session.sessionId
              ? await loadSession(session.sessionId)
              : undefined,
        );
      } catch {
        return;
      }
      if (!target || typeof target.id !== "number" || target.id < 0) return;
      const effectiveId = target.id;
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
  // every adapter consumer (chat page, composer, sidebar) on each
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
      setMasteryPathId,
      setMasterySessionMode,
      setCourseId,
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
      configureSession,
      loadSession,
      showCachedSession,
      loadMessageTrace,
      releaseMessageTrace,
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
      setMasteryPathId,
      setMasterySessionMode,
      setCourseId,
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
      configureSession,
      loadSession,
      showCachedSession,
      loadMessageTrace,
      releaseMessageTrace,
      sessionStatuses,
      state.sidebarRefreshToken,
    ],
  );

  return <ChatCtx.Provider value={value}>{children}</ChatCtx.Provider>;
}

/** Transitional state adapter for surfaces that have not moved to store selectors yet. */
export function useChatStateAdapter() {
  const ctx = useContext(ChatCtx);
  if (!ctx)
    throw new Error(
      "useChatStateAdapter must be inside ChatStateAdapterProvider",
    );
  return ctx;
}
