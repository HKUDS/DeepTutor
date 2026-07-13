"use client";

/**
 * QuizFollowupContext — owns the per-question follow-up chat state
 * (messages, sessionId, streaming flags) and the WS runners that drive it.
 *
 * Lifted out of QuizViewer so the same thread can be read from:
 *   • the quiz card itself (for the "follow-up has N messages" badge), and
 *   • the SessionViewerPanel's quiz-followup tab body, where the actual
 *     chat now happens.
 *
 * The provider also exposes ``openFollowupTab`` which forwards to whichever
 * SessionViewerPanel has registered itself via ``setOpenTabHandler`` — i.e.
 * the chat page wires the viewer panel's imperative ``openQuizFollowupTab``
 * method through this context so QuizViewer (a descendant of ChatMessages)
 * doesn't need to drill the ref through several layers of props.
 */

import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { updateNotebookEntry } from "@/lib/notebook-api";
import { shouldAppendEventContent } from "@/lib/stream";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import {
  type ChatMessage,
  type LLMSelection,
  type StreamEvent,
  UnifiedWSClient,
} from "@/lib/unified-ws";
import type { QuizQuestion } from "@/lib/quiz-types";

export interface FollowupMessage {
  role: "user" | "assistant" | "system";
  content: string;
  /**
   * Stream events that produced this message (assistant turns only).
   * Keeping the full event log on the assistant message lets the
   * follow-up tab render the same inline trace rows (``TraceFlow``) the
   * main chat uses — reasoning blocks, tool calls, stage transitions, etc.
   */
  events?: StreamEvent[];
}

export interface FollowupThreadState {
  isOpen: boolean;
  input: string;
  isStreaming: boolean;
  currentStage: string;
  sessionId: string | null;
  activeTurnId: string | null;
  messages: FollowupMessage[];
  error: string | null;
}

export function createEmptyThreadState(): FollowupThreadState {
  return {
    isOpen: false,
    input: "",
    isStreaming: false,
    currentStage: "",
    sessionId: null,
    activeTurnId: null,
    messages: [],
    error: null,
  };
}

/** Snapshot of the question + answer + judgment that a follow-up tab pins. */
export interface QuizFollowupTabContext {
  /** Stable key for the question — same key used by ``threads``. */
  questionKey: string;
  question: QuizQuestion;
  /** Plain-text user answer the learner submitted. */
  userAnswer: string;
  /** True / false / null (open-ended). */
  isCorrect: boolean | null;
  /** Image attachments associated with the answer (multi-image supported). */
  answerImages: Array<{
    id: string;
    base64: string | null;
    url: string | null;
    filename: string;
    mime: string;
    previewUrl?: string | null;
  }>;
  /** Latest AI judgment text (empty when never run). */
  aiJudgment: string;
  /** Parent quiz session id — passed through to the followup_question_context. */
  parentQuizSessionId: string | null;
  /** Notebook entry id for ``followup_session_id`` persistence. */
  notebookEntryId: number | null;
  /**
   * Persisted follow-up session id from the notebook entry, if any. When
   * non-null the tab body restores prior chat history from the backend on
   * mount instead of starting a fresh thread.
   */
  followupSessionId: string | null;
  /** UI language ("zh" / "en") for the conversation. */
  language: string;
  /** Short label for the tab strip, e.g. "Q1 follow-up". */
  tabLabel: string;
}

export interface SendMessageInput {
  questionKey: string;
  content: string;
  /** Files / images / docs the user is attaching to this turn. */
  attachments: Array<{
    type: string;
    base64?: string;
    url?: string;
    filename?: string;
    mime_type?: string;
  }>;
  config?: Record<string, unknown>;
  language?: string;
  /** Selected knowledge bases (names) for this turn. */
  knowledgeBases?: string[];
  /** Notebook/book/history/question references — same shape the
   *  main ChatPage builds for ``sendMessage``. */
  notebookReferences?: { notebook_id: string; record_ids: string[] }[];
  historyReferences?: string[];
  bookReferences?: { book_id: string; page_ids: string[] }[];
  questionNotebookReferences?: number[];
  /** Behavior persona name to apply for this turn (single, optional). */
  persona?: string;
  /** Pinned LLM selection — when null/undefined the server default applies. */
  llmSelection?: LLMSelection | null;
}

export interface HydratedFollowupMessage {
  role: "user" | "assistant" | "system";
  content: string;
  events?: StreamEvent[];
}

export interface QuizFollowupController {
  /** Returns the current thread snapshot for a question (or an empty one). */
  getThread(questionKey: string): FollowupThreadState;
  /** Patch a thread's state; merges into the existing entry. */
  updateThread(
    questionKey: string,
    updater: (prev: FollowupThreadState) => FollowupThreadState,
  ): void;
  /**
   * Hydrate a thread from previously-persisted messages (e.g. from
   * ``getSession()``). No-op when the thread already has messages — we
   * never overwrite live state with a stale snapshot.
   */
  hydrateThread(
    questionKey: string,
    sessionId: string,
    messages: HydratedFollowupMessage[],
  ): void;
  /** Send a user turn through the chat capability for this question. */
  sendMessage(input: SendMessageInput): void;
  /**
   * Deliver an answer for a turn paused on ``ask_user``. Mirrors the main
   * chat's ``submitUserReply`` — sends a same-turn ``submit_user_reply``
   * over the existing runner so the agent loop resumes without spawning a
   * new user bubble. Accepts either a flat ``text`` string (legacy
   * single-question) or a structured ``{text?, answers[]}`` (v2 path).
   */
  submitAskUserReply(
    questionKey: string,
    reply:
      | string
      | {
          text?: string;
          answers?: Array<{ questionId: string; text: string }>;
        },
  ): void;
  /** Tab open helper — forwards to whoever registered an open handler. */
  openFollowupTab(context: QuizFollowupTabContext): void;
  /**
   * Wire up the SessionViewerPanel's imperative ``openQuizFollowupTab``.
   * Called once by the chat page after it acquires its viewer-panel ref.
   * Returns an unregister fn so the chat page can clean up on unmount.
   */
  setOpenTabHandler(
    handler: ((ctx: QuizFollowupTabContext) => void) | null,
  ): void;
  /**
   * Subscribe to follow-up state changes — used by descendants that aren't
   * part of the React subtree this provider wraps (i.e. components inside
   * SessionViewerPanel rendered via a portal would still re-render through
   * the normal React tree, but the subscriber API also lets non-React
   * consumers observe state).
   */
  /* getSnapshot returns the full threads record. Components prefer to
   * select via ``useFollowupThread`` rather than reading this directly. */
  getAllThreads(): Record<string, FollowupThreadState>;
}

const QuizFollowupCtx = createContext<QuizFollowupController | null>(null);
// Public access to the threads state for components that want to react to
// thread updates without keeping their own snapshot. Updating the inner
// state triggers re-renders of subscribers via React's normal mechanism.
const QuizFollowupStateCtx = createContext<Record<string, FollowupThreadState>>(
  {},
);

interface ProviderProps {
  children: ReactNode;
}

export function QuizFollowupProvider({ children }: ProviderProps) {
  const [threads, setThreads] = useState<Record<string, FollowupThreadState>>(
    {},
  );
  const threadsRef = useRef<Record<string, FollowupThreadState>>({});
  const runnersRef = useRef<
    Map<string, { questionKey: string; client: UnifiedWSClient }>
  >(new Map());
  // Notebook entry ids per question — captured from sendMessage so the
  // ``session`` event handler can persist ``followup_session_id`` on the
  // matching entry once the backend assigns one.
  const entryIdsRef = useRef<Map<string, number | null>>(new Map());
  const openTabHandlerRef = useRef<
    ((ctx: QuizFollowupTabContext) => void) | null
  >(null);

  useEffect(() => {
    threadsRef.current = threads;
  }, [threads]);

  useEffect(
    () => () => {
      runnersRef.current.forEach(({ client }) => client.disconnect());
      runnersRef.current.clear();
    },
    [],
  );

  const updateThread = useCallback(
    (
      key: string,
      updater: (prev: FollowupThreadState) => FollowupThreadState,
    ) => {
      setThreads((prev) => ({
        ...prev,
        [key]: updater(prev[key] ?? createEmptyThreadState()),
      }));
    },
    [],
  );

  const handleThreadEvent = useCallback(
    (key: string, event: StreamEvent) => {
      if (event.type === "session") {
        const metadata = (event.metadata ?? {}) as {
          session_id?: string;
          turn_id?: string;
        };
        const nextSessionId = metadata.session_id || event.session_id || "";
        const nextTurnId = metadata.turn_id || event.turn_id || null;
        if (!nextSessionId) return;
        updateThread(key, (prev) => ({
          ...prev,
          sessionId: nextSessionId,
          activeTurnId: nextTurnId,
        }));
        const runner = runnersRef.current.get(key);
        if (runner) runner.questionKey = nextSessionId;
        const entryId = entryIdsRef.current.get(key);
        if (entryId) {
          void updateNotebookEntry(entryId, {
            followup_session_id: nextSessionId,
          }).catch(() => {});
        }
        return;
      }

      if (event.type === "done") {
        updateThread(key, (prev) => ({
          ...prev,
          isStreaming: false,
          currentStage: "",
          activeTurnId: null,
        }));
        const runner = runnersRef.current.get(key);
        runner?.client.disconnect();
        runnersRef.current.delete(key);
        return;
      }

      updateThread(key, (prev) => {
        const next = {
          ...prev,
          activeTurnId: event.turn_id || prev.activeTurnId,
        };
        if (event.type === "stage_start") {
          next.currentStage = event.stage;
        } else if (event.type === "stage_end") {
          next.currentStage = "";
        } else if (event.type === "error") {
          next.error = event.content || prev.error;
          const terminal = Boolean(
            ((event.metadata ?? {}) as { turn_terminal?: boolean })
              .turn_terminal,
          );
          if (terminal) {
            next.isStreaming = false;
            next.currentStage = "";
            next.activeTurnId = null;
          }
        }
        // Append the streaming event to the latest assistant message's
        // event log so the trace surface can render the full reasoning /
        // tool-call narrative — matching the main chat's behaviour.
        const messages = [...prev.messages];
        let last = messages[messages.length - 1];
        if (!last || last.role !== "assistant") {
          messages.push({ role: "assistant", content: "", events: [event] });
        } else {
          messages[messages.length - 1] = {
            ...last,
            events: [...(last.events ?? []), event],
          };
        }
        last = messages[messages.length - 1];
        if (
          last &&
          last.role === "assistant" &&
          shouldAppendEventContent(event)
        ) {
          messages[messages.length - 1] = {
            ...last,
            content: `${last.content}${event.content}`,
          };
        }
        next.messages = messages;
        return next;
      });
    },
    [updateThread],
  );

  const ensureRunner = useCallback(
    (key: string) => {
      const existing = runnersRef.current.get(key);
      if (existing) {
        if (!existing.client.connected) existing.client.connect();
        return existing;
      }
      const record = {
        questionKey: key,
        client: new UnifiedWSClient(
          (event) => handleThreadEvent(key, event),
          () => {
            const current = threadsRef.current[key];
            if (current?.isStreaming) {
              updateThread(key, (prev) => ({
                ...prev,
                isStreaming: false,
                currentStage: "",
                activeTurnId: null,
                error:
                  prev.error ||
                  "Follow-up chat failed because the connection closed.",
              }));
            }
          },
        ),
      };
      runnersRef.current.set(key, record);
      record.client.connect();
      return record;
    },
    [handleThreadEvent, updateThread],
  );

  const sendThroughRunner = useCallback(
    function send(key: string, message: ChatMessage, attempt = 0) {
      const runner = ensureRunner(key);
      if (!runner.client.connected) {
        if (attempt >= 10) {
          updateThread(key, (prev) => ({
            ...prev,
            isStreaming: false,
            currentStage: "",
            error: "Follow-up chat failed to connect.",
          }));
          return;
        }
        window.setTimeout(() => send(key, message, attempt + 1), 200);
        return;
      }
      runner.client.send(message);
    },
    [ensureRunner, updateThread],
  );

  const sendMessage = useCallback(
    (input: SendMessageInput) => {
      const current =
        threadsRef.current[input.questionKey] ?? createEmptyThreadState();
      const content = input.content.trim();
      if (!content && input.attachments.length === 0) return;
      if (current.isStreaming) return;

      updateThread(input.questionKey, (prev) => ({
        ...prev,
        isOpen: true,
        input: "",
        isStreaming: true,
        error: null,
        messages: [...prev.messages, { role: "user", content }],
      }));

      sendThroughRunner(input.questionKey, {
        type: "start_turn",
        content,
        tools: [],
        capability: "chat",
        knowledge_bases: input.knowledgeBases ?? [],
        session_id: current.sessionId,
        attachments: input.attachments,
        language: input.language,
        config: input.config,
        notebook_references: input.notebookReferences,
        history_references: input.historyReferences,
        book_references: input.bookReferences,
        question_notebook_references: input.questionNotebookReferences,
        // Always send the key (possibly ""): an absent key makes the backend
        // fall back to the session's stored persona preference, which would
        // turn this surface's deliberately per-turn persona into a sticky
        // one. Explicit "" keeps each follow-up turn persona-free unless
        // picked for that turn.
        persona: input.persona ?? "",
        llm_selection: input.llmSelection ?? null,
      });
    },
    [sendThroughRunner, updateThread],
  );

  const submitAskUserReply = useCallback(
    (
      key: string,
      reply:
        | string
        | {
            text?: string;
            answers?: Array<{ questionId: string; text: string }>;
          },
    ) => {
      const current = threadsRef.current[key];
      const turnId = current?.activeTurnId;
      if (!current || !turnId) return;
      // Allow submission either while the turn is still streaming OR while
      // it's paused on an unresolved ask_user card (matches the main chat's
      // ``submitUserReply`` guard).
      const pendingAskUser = current.messages.some((m) =>
        hasPendingAskUser(m.events, turnId),
      );
      if (!current.isStreaming && !pendingAskUser) return;

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
      // Flip the thread back into the streaming state so the trace surface
      // shows the spinner while the resumed iteration runs. The runner is
      // already alive (ask_user pauses without disconnecting), so we just
      // forward the reply through it.
      updateThread(key, (prev) => ({
        ...prev,
        isStreaming: true,
        error: null,
      }));
      sendThroughRunner(key, message);
    },
    [sendThroughRunner, updateThread],
  );

  const openFollowupTab = useCallback((context: QuizFollowupTabContext) => {
    entryIdsRef.current.set(context.questionKey, context.notebookEntryId);
    const handler = openTabHandlerRef.current;
    if (handler) handler(context);
  }, []);

  const hydrateThread = useCallback(
    (key: string, sessionId: string, messages: HydratedFollowupMessage[]) => {
      // Skip when the thread already holds local state — we never
      // overwrite an active conversation with a stale snapshot. The
      // ``sessionId`` check covers the case where the in-memory thread
      // is empty but we already wired a session id from a prior call.
      const current = threadsRef.current[key];
      if (current && (current.messages.length > 0 || current.isStreaming)) {
        return;
      }
      updateThread(key, (prev) => ({
        ...prev,
        sessionId,
        messages: messages.map((m) => ({
          role: m.role,
          content: m.content,
          events: m.events ?? [],
        })),
      }));
    },
    [updateThread],
  );

  const setOpenTabHandler = useCallback(
    (handler: ((ctx: QuizFollowupTabContext) => void) | null) => {
      openTabHandlerRef.current = handler;
    },
    [],
  );

  const getThread = useCallback((key: string): FollowupThreadState => {
    return threadsRef.current[key] ?? createEmptyThreadState();
  }, []);

  const getAllThreads = useCallback(() => threadsRef.current, []);

  const controller = useMemo<QuizFollowupController>(
    () => ({
      getThread,
      updateThread,
      hydrateThread,
      sendMessage,
      submitAskUserReply,
      openFollowupTab,
      setOpenTabHandler,
      getAllThreads,
    }),
    [
      getThread,
      updateThread,
      hydrateThread,
      sendMessage,
      submitAskUserReply,
      openFollowupTab,
      setOpenTabHandler,
      getAllThreads,
    ],
  );

  return (
    <QuizFollowupCtx.Provider value={controller}>
      <QuizFollowupStateCtx.Provider value={threads}>
        {children}
      </QuizFollowupStateCtx.Provider>
    </QuizFollowupCtx.Provider>
  );
}

export function useQuizFollowupController(): QuizFollowupController {
  const ctx = useContext(QuizFollowupCtx);
  if (!ctx) {
    throw new Error(
      "useQuizFollowupController must be used inside a QuizFollowupProvider",
    );
  }
  return ctx;
}

/** Returns the live thread snapshot for a question key, re-rendering on
 *  every update. Returns the empty thread when no entry exists yet. */
export function useFollowupThread(questionKey: string): FollowupThreadState {
  const threads = useContext(QuizFollowupStateCtx);
  return threads[questionKey] ?? createEmptyThreadState();
}

/** Returns the full threads record — used by QuizViewer for "any thread
 *  with messages?" lookups across all questions in a quiz. */
export function useAllFollowupThreads(): Record<string, FollowupThreadState> {
  return useContext(QuizFollowupStateCtx);
}
