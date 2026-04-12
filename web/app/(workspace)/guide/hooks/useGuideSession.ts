import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { apiUrl } from "@/lib/api";
import {
  SessionState,
  ChatMessage,
  KnowledgePoint,
  INITIAL_SESSION_STATE,
  PageStatus,
} from "../types";
import {
  loadFromStorage,
  removeFromStorage,
  saveToStorage,
  persistState,
  mergeWithDefaults,
  STORAGE_KEYS,
} from "@/lib/persistence";
import { debounce } from "@/lib/debounce";

const GUIDE_CHAT_KEY = "guide_chat_messages";
const GUIDE_SESSION_EXCLUDE: (keyof SessionState)[] = ["html_pages"];

type PagePayload = {
  page_statuses?: Record<number, PageStatus>;
  page_errors?: Record<number, string>;
  html_pages?: Record<number, string>;
  progress?: number;
  current_index?: number;
  status?: SessionState["status"];
};

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError") {
    return true;
  }
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    return msg.includes("abort") || msg.includes("aborted");
  }
  return false;
}

async function fetchJsonWithTimeout(
  input: string,
  init: RequestInit,
  timeoutMs = 45000,
): Promise<{ response: Response; data: unknown }> {
  const controller = new AbortController();
  const timer = window.setTimeout(
    () => controller.abort("guide_request_timeout"),
    timeoutMs,
  );
  try {
    const response = await fetch(input, { ...init, signal: controller.signal });
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    return { response, data };
  } catch (error) {
    if (isAbortError(error)) {
      throw new Error("GUIDE_REQUEST_TIMEOUT");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export function useGuideSession() {
  const isHydrated = useRef(false);
  const pollingRef = useRef<number | null>(null);

  const [sessionState, setSessionState] = useState<SessionState>(
    INITIAL_SESSION_STATE,
  );
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [sessionError, setSessionError] = useState("");
  const hasUnresolvedPages = Object.values(sessionState.page_statuses).some(
    (status) => status === "pending" || status === "generating",
  );

  const stopPolling = useCallback(() => {
    if (pollingRef.current !== null) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const clearPersistedGuideState = useCallback(() => {
    removeFromStorage(STORAGE_KEYS.GUIDE_SESSION);
    removeFromStorage(GUIDE_CHAT_KEY);
  }, []);

  const resetGuideState = useCallback(
    (message?: string) => {
      stopPolling();
      clearPersistedGuideState();
      setSessionState(INITIAL_SESSION_STATE);
      setIsLoading(false);
      setLoadingMessage("");
      setSessionError("");
      setChatMessages(
        message
          ? [
              {
                id: `reset-${Date.now()}`,
                role: "system",
                content: message,
                timestamp: Date.now(),
              },
            ]
          : [],
      );
    },
    [clearPersistedGuideState, stopPolling],
  );

  const isSessionMissingResponse = useCallback(
    (status: number, data: unknown) => {
      if (status === 404) return true;
      if (!data || typeof data !== "object") return false;

      const payload = data as Record<string, unknown>;
      const error = typeof payload.error === "string" ? payload.error : "";
      const detail = typeof payload.detail === "string" ? payload.detail : "";

      return (
        error === "Session does not exist" ||
        detail === "Session not found" ||
        detail === "Session not found or no HTML content"
      );
    },
    [],
  );

  const saveSessionState = useMemo(
    () =>
      debounce((state: SessionState) => {
        const toSave = persistState(state, GUIDE_SESSION_EXCLUDE);
        saveToStorage(STORAGE_KEYS.GUIDE_SESSION, toSave);
      }, 500),
    [],
  );

  const saveChatMessages = useMemo(
    () =>
      debounce((messages: ChatMessage[]) => {
        saveToStorage(GUIDE_CHAT_KEY, messages);
      }, 500),
    [],
  );

  const addLoadingMessage = useCallback((message: string) => {
    const loadingMsg: ChatMessage = {
      id: `loading-${Date.now()}`,
      role: "system",
      content: `⏳ ${message}`,
      timestamp: Date.now(),
    };
    setChatMessages((prev) => [...prev, loadingMsg]);
    return loadingMsg.id;
  }, []);

  const removeLoadingMessage = useCallback((id: string) => {
    setChatMessages((prev) => prev.filter((msg) => msg.id !== id));
  }, []);

  const addChatMessage = useCallback(
    (
      role: "user" | "assistant" | "system",
      content: string,
      id?: string,
      knowledge_index?: number | null,
    ) => {
      setChatMessages((prev) => [
        ...prev,
        {
          id: id || `${role}-${Date.now()}`,
          role,
          content,
          timestamp: Date.now(),
          knowledge_index,
        },
      ]);
    },
    [],
  );

  const mergePageState = useCallback((payload: PagePayload) => {
    setSessionState((prev) => {
      const mergedHtmlPages = {
        ...prev.html_pages,
        ...(payload.html_pages || {}),
      };
      const mergedStatuses = {
        ...prev.page_statuses,
        ...(payload.page_statuses || {}),
      };
      const mergedErrors = {
        ...prev.page_errors,
        ...(payload.page_errors || {}),
      };

      let currentIndex = prev.current_index;
      if (typeof payload.current_index === "number") {
        currentIndex = payload.current_index;
      }

      if (currentIndex < 0) {
        const firstReadyKey = Object.keys(mergedStatuses).find(
          (key) => mergedStatuses[Number(key)] === "ready",
        );
        if (firstReadyKey !== undefined) {
          currentIndex = Number(firstReadyKey);
        }
      }

      return {
        ...prev,
        html_pages: mergedHtmlPages,
        page_statuses: mergedStatuses,
        page_errors: mergedErrors,
        current_index: currentIndex,
        progress: payload.progress ?? prev.progress,
        status: payload.status ?? prev.status,
      };
    });
  }, []);

  const fetchPageStatuses = useCallback(async () => {
    if (!sessionState.session_id) return;

    try {
      const res = await fetch(
        apiUrl(`/api/v1/guide/session/${sessionState.session_id}/pages`),
      );
      let data: unknown = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }

      if (!res.ok && isSessionMissingResponse(res.status, data)) {
        resetGuideState(
          "⚠️ Guided learning session expired. Please generate a new learning plan.",
        );
        return;
      }

      if (!res.ok || !data || typeof data !== "object") {
        return;
      }

      const payload = data as Record<string, unknown>;
      const pageStatuses =
        (payload.page_statuses as Record<number, PageStatus> | undefined) || {};
      const allStatuses = Object.values(pageStatuses);
      const resolved =
        allStatuses.length > 0 &&
        allStatuses.every((status) => status === "ready" || status === "failed");

      mergePageState({
        page_statuses: pageStatuses,
        page_errors:
          (payload.page_errors as Record<number, string> | undefined) || {},
        html_pages:
          (payload.html_pages as Record<number, string> | undefined) || {},
        progress: typeof payload.progress === "number" ? payload.progress : 0,
        current_index:
          typeof payload.current_index === "number"
            ? payload.current_index
            : undefined,
        status:
          typeof payload.status === "string"
            ? (payload.status as SessionState["status"])
            : undefined,
      });

      if (resolved) {
        stopPolling();
      }
    } catch (err) {
      console.error("Failed to fetch page statuses:", err);
    }
  }, [
    isSessionMissingResponse,
    mergePageState,
    resetGuideState,
    sessionState.session_id,
    stopPolling,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;

    const restoreSession = async () => {
      const persistedSession = loadFromStorage<Partial<SessionState>>(
        STORAGE_KEYS.GUIDE_SESSION,
        {},
      );
      const persistedChat = loadFromStorage<ChatMessage[]>(GUIDE_CHAT_KEY, []);
      const persistedSessionId =
        typeof persistedSession.session_id === "string"
          ? persistedSession.session_id
          : null;

      if (!persistedSessionId) {
        if (
          Object.keys(persistedSession).length > 0 ||
          persistedChat.length > 0
        ) {
          clearPersistedGuideState();
        }
        isHydrated.current = true;
        return;
      }

      try {
        const res = await fetch(
          apiUrl(`/api/v1/guide/session/${persistedSessionId}`),
        );
        let data: unknown = null;
        try {
          data = await res.json();
        } catch {
          data = null;
        }

        if (!res.ok && isSessionMissingResponse(res.status, data)) {
          if (!cancelled) {
            resetGuideState(
              "⚠️ Previous guided learning session expired. Please generate a new learning plan.",
            );
          }
          return;
        }

        if (!cancelled) {
          setSessionState((prev) =>
            mergeWithDefaults(persistedSession, prev, GUIDE_SESSION_EXCLUDE),
          );
          if (persistedChat.length > 0) {
            setChatMessages(persistedChat);
          }
        }
      } catch {
        if (!cancelled) {
          setSessionState((prev) =>
            mergeWithDefaults(persistedSession, prev, GUIDE_SESSION_EXCLUDE),
          );
          if (persistedChat.length > 0) {
            setChatMessages(persistedChat);
          }
        }
      } finally {
        isHydrated.current = true;
      }
    };

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, [clearPersistedGuideState, isSessionMissingResponse, resetGuideState]);

  useEffect(() => {
    if (isHydrated.current) {
      saveSessionState(sessionState);
    }
  }, [sessionState, saveSessionState]);

  useEffect(() => {
    if (isHydrated.current) {
      saveChatMessages(chatMessages);
    }
  }, [chatMessages, saveChatMessages]);

  useEffect(() => {
    if (
      sessionState.status !== "learning" ||
      !sessionState.session_id ||
      !hasUnresolvedPages
    ) {
      stopPolling();
      return;
    }

    void fetchPageStatuses();
    if (pollingRef.current === null) {
      pollingRef.current = window.setInterval(() => {
        void fetchPageStatuses();
      }, 2000);
    }

    return () => {
      stopPolling();
    };
  }, [
    fetchPageStatuses,
    hasUnresolvedPages,
    sessionState.session_id,
    sessionState.status,
    stopPolling,
  ]);

  const createSession = useCallback(
    async (
      userInput: string,
      notebookReferences?: Array<{ notebook_id: string; record_ids: string[] }>,
    ) => {
      const trimmedInput = userInput.trim();
      if (!trimmedInput) return;

      stopPolling();
      setIsLoading(true);
      setLoadingMessage("Designing your guided learning plan...");
      setSessionError("");
      const loadingId = addLoadingMessage(
        "Designing your guided learning plan...",
      );

      try {
        const browserLanguage =
          typeof navigator !== "undefined" && navigator.language
            ? navigator.language
            : "zh";
        const requestedLanguage = browserLanguage.toLowerCase().startsWith("zh")
          ? "zh"
          : "en";

        const { response, data } = await fetchJsonWithTimeout(
          apiUrl("/api/v1/guide/create_session"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_input: trimmedInput,
              language: requestedLanguage,
              ...(notebookReferences?.length
                ? { notebook_references: notebookReferences }
                : {}),
            }),
          },
          45000,
        );

        removeLoadingMessage(loadingId);
        setIsLoading(false);
        setLoadingMessage("");

        const payload = data as Record<string, unknown> | null;
        if (!response.ok) {
          const message =
            (payload?.detail as string) ||
            (payload?.error as string) ||
            `Request failed (${response.status})`;
          setSessionError(message);
          addChatMessage("system", `❌ Failed to create session: ${message}`, `error-${Date.now()}`);
          return;
        }

        if (payload?.success) {
          const initialStatuses: Record<number, PageStatus> = {};
          ((payload.knowledge_points as KnowledgePoint[]) || []).forEach(
            (_kp: KnowledgePoint, idx: number) => {
              initialStatuses[idx] = "pending";
            },
          );

          setSessionState({
            session_id: String(payload.session_id || ""),
            topic: trimmedInput,
            knowledge_points: (payload.knowledge_points as KnowledgePoint[]) || [],
            current_index: -1,
            html_pages: {},
            page_statuses: initialStatuses,
            page_errors: {},
            status: "initialized",
            progress: 0,
            summary: "",
          });

          const points = (payload.knowledge_points as KnowledgePoint[]) || [];
          const planMessage = `📚 Learning plan generated with **${payload.total_points || points.length}** knowledge points:\n\n${points.map((kp: KnowledgePoint, idx: number) => `${idx + 1}. ${kp.knowledge_title}`).join("\n")}\n\nClick "Start Learning" to generate all interactive pages in parallel.`;
          setChatMessages([
            {
              id: "plan",
              role: "system",
              content: planMessage,
              timestamp: Date.now(),
            },
          ]);
          setSessionError("");
        } else {
          const message = String(payload?.error || "Unknown error");
          setSessionError(message);
          addChatMessage(
            "system",
            `❌ Failed to create session: ${message}`,
            `error-${Date.now()}`,
          );
        }
      } catch (err) {
        removeLoadingMessage(loadingId);
        setIsLoading(false);
        setLoadingMessage("");
        const isTimeout = err instanceof Error && err.message === "GUIDE_REQUEST_TIMEOUT";
        if (!isTimeout) {
          console.error("Failed to create session:", err);
        }
        const message = isTimeout || isAbortError(err)
          ? "❌ Request timed out. Please check model configuration and retry."
          : "❌ Failed to create session, please try again later";
        setSessionError(message.replace(/^❌\s*/, ""));
        addChatMessage(
          "system",
          message,
          `error-${Date.now()}`,
        );
      }
    },
    [addChatMessage, addLoadingMessage, removeLoadingMessage, stopPolling],
  );

  const startLearning = useCallback(async () => {
    if (!sessionState.session_id) return;

    setIsLoading(true);
    setLoadingMessage("Generating interactive learning pages...");
    const loadingId = addLoadingMessage(
      "Generating interactive learning pages...",
    );

    try {
      const res = await fetch(apiUrl("/api/v1/guide/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionState.session_id }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);

      if (isSessionMissingResponse(res.status, data)) {
        resetGuideState(
          "⚠️ Guided learning session expired. Please generate a new learning plan.",
        );
        return;
      }

      setIsLoading(false);
      setLoadingMessage("");

      if (data.success) {
        setSessionState((prev) => ({
          ...prev,
          current_index: typeof data.current_index === "number" ? data.current_index : 0,
          html_pages: data.html
            ? { ...prev.html_pages, 0: data.html as string }
            : prev.html_pages,
          page_statuses: {
            ...prev.page_statuses,
            ...(data.page_statuses || {}),
          },
          status: "learning",
          progress: data.progress || 0,
        }));

        addChatMessage(
          "system",
          data.message ||
            "Interactive pages are generating in parallel. Open any page once it becomes ready.",
          `start-${Date.now()}`,
        );
      } else {
        addChatMessage(
          "system",
          `❌ Failed to start learning: ${data.error || "Unknown error"}`,
          `error-${Date.now()}`,
        );
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");
      console.error("Failed to start learning:", err);
      addChatMessage(
        "system",
        "❌ Failed to start learning, please try again later",
        `error-${Date.now()}`,
      );
    }
  }, [
    addChatMessage,
    addLoadingMessage,
    isSessionMissingResponse,
    removeLoadingMessage,
    resetGuideState,
    sessionState.session_id,
  ]);

  const navigateTo = useCallback(
    async (knowledgeIndex: number) => {
      if (!sessionState.session_id) return;

      setSessionState((prev) => ({
        ...prev,
        current_index: knowledgeIndex,
      }));

      if (
        sessionState.page_statuses[knowledgeIndex] === "ready" &&
        sessionState.html_pages[knowledgeIndex]
      ) {
        return;
      }

      try {
        const res = await fetch(apiUrl("/api/v1/guide/navigate"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionState.session_id,
            knowledge_index: knowledgeIndex,
          }),
        });
        const data = await res.json();

        if (isSessionMissingResponse(res.status, data)) {
          resetGuideState(
            "⚠️ Guided learning session expired. Please generate a new learning plan.",
          );
          return;
        }

        if (data.success) {
          mergePageState({
            current_index: knowledgeIndex,
            html_pages: data.html ? { [knowledgeIndex]: data.html as string } : {},
            page_statuses: data.page_status
              ? { [knowledgeIndex]: data.page_status as PageStatus }
              : {},
            page_errors: data.page_error ? { [knowledgeIndex]: data.page_error as string } : {},
            progress: typeof data.progress === "number" ? data.progress : undefined,
          });
        } else {
          addChatMessage(
            "system",
            `❌ Failed to open page: ${data.error || "Unknown error"}`,
            `error-${Date.now()}`,
          );
        }
      } catch (err) {
        console.error("Failed to navigate knowledge point:", err);
      }
    },
    [
      addChatMessage,
      isSessionMissingResponse,
      mergePageState,
      resetGuideState,
      sessionState.html_pages,
      sessionState.page_statuses,
      sessionState.session_id,
    ],
  );

  const retryPage = useCallback(
    async (pageIndex: number) => {
      if (!sessionState.session_id) return;

      try {
        const res = await fetch(apiUrl("/api/v1/guide/retry_page"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionState.session_id,
            page_index: pageIndex,
          }),
        });
        const data = await res.json();

        if (isSessionMissingResponse(res.status, data)) {
          resetGuideState(
            "⚠️ Guided learning session expired. Please generate a new learning plan.",
          );
          return;
        }

        if (data.success) {
          mergePageState({
            page_statuses: { [pageIndex]: "pending" },
            page_errors: { [pageIndex]: "" },
          });
          addChatMessage(
            "system",
            data.message || `Retrying page ${pageIndex + 1}.`,
            `retry-${Date.now()}`,
            pageIndex,
          );
        }
      } catch (err) {
        console.error("Failed to retry page:", err);
      }
    },
    [
      addChatMessage,
      isSessionMissingResponse,
      mergePageState,
      resetGuideState,
      sessionState.session_id,
    ],
  );

  const completeLearning = useCallback(async () => {
    if (!sessionState.session_id) return;

    setIsLoading(true);
    setLoadingMessage("Generating learning summary...");
    const loadingId = addLoadingMessage("Generating learning summary...");

    try {
      const res = await fetch(apiUrl("/api/v1/guide/complete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionState.session_id }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");

      if (isSessionMissingResponse(res.status, data)) {
        resetGuideState(
          "⚠️ Guided learning session expired. Please generate a new learning plan.",
        );
        return;
      }

      if (data.success) {
        stopPolling();
        setSessionState((prev) => ({
          ...prev,
          status: "completed",
          summary: data.summary || "",
          progress: 100,
        }));
        addChatMessage(
          "system",
          data.message || "Guided learning completed.",
          `complete-${Date.now()}`,
        );
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");
      console.error("Failed to complete learning:", err);
    }
  }, [
    addChatMessage,
    addLoadingMessage,
    isSessionMissingResponse,
    removeLoadingMessage,
    resetGuideState,
    sessionState.session_id,
    stopPolling,
  ]);

  const sendMessage = useCallback(
    async (message: string) => {
      if (
        !message.trim() ||
        !sessionState.session_id ||
        sessionState.current_index < 0 ||
        sessionState.page_statuses[sessionState.current_index] !== "ready"
      ) {
        return;
      }

      const knowledgeIndex = sessionState.current_index;
      addChatMessage(
        "user",
        message,
        `user-${Date.now()}`,
        knowledgeIndex,
      );
      const loadingId = addLoadingMessage("Thinking...");

      try {
        const res = await fetch(apiUrl("/api/v1/guide/chat"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionState.session_id,
            message,
            knowledge_index: knowledgeIndex,
          }),
        });
        const data = await res.json();

        removeLoadingMessage(loadingId);

        if (isSessionMissingResponse(res.status, data)) {
          resetGuideState(
            "⚠️ Guided learning session expired. Please generate a new learning plan.",
          );
          return;
        }

        if (data.success) {
          addChatMessage(
            "assistant",
            data.answer || "",
            `assistant-${Date.now()}`,
            typeof data.knowledge_index === "number"
              ? data.knowledge_index
              : knowledgeIndex,
          );
        } else {
          addChatMessage(
            "assistant",
            `❌ Error: ${data.error || "Failed to respond"}`,
            `error-${Date.now()}`,
            knowledgeIndex,
          );
        }
      } catch (err) {
        removeLoadingMessage(loadingId);
        console.error("Failed to send message:", err);
        addChatMessage(
          "assistant",
          "❌ Failed to send message, please try again later",
          `error-${Date.now()}`,
          knowledgeIndex,
        );
      }
    },
    [
      addChatMessage,
      addLoadingMessage,
      isSessionMissingResponse,
      removeLoadingMessage,
      resetGuideState,
      sessionState.current_index,
      sessionState.page_statuses,
      sessionState.session_id,
    ],
  );

  const fixHtml = useCallback(
    async (bugDescription: string) => {
      if (
        !sessionState.session_id ||
        !bugDescription.trim() ||
        sessionState.current_index < 0
      ) {
        return false;
      }

      const currentIndex = sessionState.current_index;
      const loadingId = addLoadingMessage("Fixing HTML page...");

      try {
        const res = await fetch(apiUrl("/api/v1/guide/fix_html"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionState.session_id,
            bug_description: bugDescription,
          }),
        });
        const data = await res.json();

        removeLoadingMessage(loadingId);

        if (isSessionMissingResponse(res.status, data)) {
          resetGuideState(
            "⚠️ Guided learning session expired. Please generate a new learning plan.",
          );
          return false;
        }

        if (data.success) {
          mergePageState({
            html_pages: {
              [currentIndex]:
                (data.html as string) || sessionState.html_pages[currentIndex],
            },
            page_statuses: { [currentIndex]: "ready" },
          });
          addChatMessage(
            "system",
            "✅ HTML page has been fixed!",
            `fix-${Date.now()}`,
            currentIndex,
          );
          return true;
        }

        addChatMessage(
          "system",
          `❌ Fix failed: ${data.error || "Unknown error"}`,
          `error-${Date.now()}`,
          currentIndex,
        );
        return false;
      } catch (err) {
        removeLoadingMessage(loadingId);
        console.error("Failed to fix HTML:", err);
        addChatMessage(
          "system",
          "❌ Fix failed, please try again later",
          `error-${Date.now()}`,
          currentIndex,
        );
        return false;
      }
    },
    [
      addChatMessage,
      addLoadingMessage,
      isSessionMissingResponse,
      mergePageState,
      removeLoadingMessage,
      resetGuideState,
      sessionState.current_index,
      sessionState.html_pages,
      sessionState.session_id,
    ],
  );

  const resetSession = useCallback(async () => {
    const sessionId = sessionState.session_id;
    resetGuideState();

    if (!sessionId) return;
    try {
      await fetch(apiUrl("/api/v1/guide/reset"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch (err) {
      console.error("Failed to reset session on backend:", err);
    }
  }, [resetGuideState, sessionState.session_id]);

  const loadSession = useCallback(
    async (sessionId: string) => {
      stopPolling();
      setIsLoading(true);
      setLoadingMessage("Loading session...");

      try {
        const res = await fetch(apiUrl(`/api/v1/guide/session/${sessionId}`));
        if (!res.ok) {
          setIsLoading(false);
          setLoadingMessage("");
          addChatMessage(
            "system",
            "Failed to load session.",
            `error-${Date.now()}`,
          );
          return;
        }

        const data = await res.json();
        const knowledgePoints: KnowledgePoint[] =
          data.knowledge_points || [];
        const htmlPages: Record<number, string> = {};
        const pageStatuses: Record<number, PageStatus> = {};
        const pageErrors: Record<number, string> = {};

        if (data.html_pages && typeof data.html_pages === "object") {
          for (const [key, val] of Object.entries(data.html_pages)) {
            htmlPages[Number(key)] = val as string;
          }
        }
        if (data.page_statuses && typeof data.page_statuses === "object") {
          for (const [key, val] of Object.entries(data.page_statuses)) {
            pageStatuses[Number(key)] = val as PageStatus;
          }
        }
        if (data.page_errors && typeof data.page_errors === "object") {
          for (const [key, val] of Object.entries(data.page_errors)) {
            pageErrors[Number(key)] = val as string;
          }
        }

        const restoredMessages: ChatMessage[] = [];
        if (Array.isArray(data.chat_history)) {
          for (const msg of data.chat_history) {
            if (msg.role && msg.content) {
              restoredMessages.push({
                id: `restored-${msg.timestamp || Date.now()}-${Math.random()}`,
                role: msg.role as ChatMessage["role"],
                content: msg.content,
                timestamp: msg.timestamp ? msg.timestamp * 1000 : Date.now(),
                knowledge_index:
                  typeof msg.knowledge_index === "number"
                    ? msg.knowledge_index
                    : undefined,
              });
            }
          }
        }

        setSessionState({
          session_id: data.session_id || sessionId,
          topic: data.notebook_name || "",
          knowledge_points: knowledgePoints,
          current_index:
            typeof data.current_index === "number" ? data.current_index : -1,
          html_pages: htmlPages,
          page_statuses: pageStatuses,
          page_errors: pageErrors,
          status: data.status || "initialized",
          progress:
            typeof data.progress === "number"
              ? data.progress
              : knowledgePoints.length > 0
                ? Math.round(
                    (Object.values(pageStatuses).filter((s) => s === "ready")
                      .length /
                      knowledgePoints.length) *
                      100,
                  )
                : 0,
          summary: data.summary || "",
        });

        setChatMessages(restoredMessages);
        setIsLoading(false);
        setLoadingMessage("");
      } catch (err) {
        console.error("Failed to load session:", err);
        setIsLoading(false);
        setLoadingMessage("");
        addChatMessage(
          "system",
          "Failed to load session, please try again later.",
          `error-${Date.now()}`,
        );
      }
    },
    [addChatMessage, stopPolling],
  );

  const canStart =
    sessionState.status === "initialized" &&
    sessionState.knowledge_points.length > 0;
  const isCompleted = sessionState.status === "completed";
  const readyCount = Object.values(sessionState.page_statuses).filter(
    (status) => status === "ready",
  ).length;
  const allPagesReady =
    sessionState.knowledge_points.length > 0 &&
    readyCount === sessionState.knowledge_points.length;
  const currentPageStatus =
    sessionState.current_index >= 0
      ? sessionState.page_statuses[sessionState.current_index]
      : undefined;
  const currentPageReady = currentPageStatus === "ready";

  return {
    sessionState,
    chatMessages,
    isLoading,
    loadingMessage,
    sessionError,
    canStart,
    isCompleted,
    readyCount,
    allPagesReady,
    currentPageStatus,
    currentPageReady,
    createSession,
    startLearning,
    navigateTo,
    retryPage,
    completeLearning,
    sendMessage,
    fixHtml,
    resetSession,
    loadSession,
  };
}
