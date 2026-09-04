"use client";

import dynamic from "next/dynamic";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useChatRouteSession } from "@/features/chat/controllers/useChatRouteSession";

import {
  GraduationCap,
  NotebookPen,
  PenLine,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedRecord } from "@/lib/notebook-selection-types";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import ChatComposer from "@/components/chat/home/ChatComposer";
import type { ContextBudget } from "@/components/chat/home/ContextBudgetChip";
import { ChatMessageList } from "@/features/chat/messages";
import { TurnNavigator } from "@/components/chat/home/TurnNavigator";
import SessionLoadingView from "@/components/chat/home/SessionLoadingView";
import {
  SESSION_LOAD_TIMEOUT_MS,
  shouldSurfaceLoadFailure,
} from "@/lib/session-load";
import StarterSuggestions from "@/components/chat/home/StarterSuggestions";
// Imported eagerly so the drawer shell is always mounted off-screen —
// clicking a chip becomes a single CSS class flip, no chunk fetch + double
// render. The heavy renderers inside still load lazily.
import FilePreviewDrawer from "@/components/chat/preview/FilePreviewDrawer";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import Tooltip from "@/components/common/Tooltip";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import {
  QuizFollowupProvider,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import {
  GeogebraTabProvider,
  useGeogebraTabOpener,
} from "@/context/GeogebraTabContext";
import { BookmarkPlus, Download, PanelRight } from "lucide-react";
import {
  useChatStateAdapter,
  type MessageAttachment,
  type MessageRequestSnapshot,
} from "@/features/chat/ChatStateAdapter";
import { useAppShell } from "@/context/AppShellContext";

import {
  WATCHING_ASK_EVENT,
  WatchingPane,
} from "@/components/watching/WatchingPane";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import type { LLMSelection, StreamEvent } from "@/features/chat/model/protocol";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";
import {
  fileToPendingAttachment,
  selectAttachmentFiles,
  type PendingAttachment,
} from "@/features/chat/controllers/pending-attachments";
import { readChatLaunchIntent } from "@/lib/chat-launch-intent";
import { useAttachmentLimits } from "@/lib/attachment-limits";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useSetupSync } from "@/hooks/useSetupSync";
import { listCourses, type StudyCourse } from "@/lib/courses-api";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import {
  fetchSessionAskHint,
  updateSessionOrganization,
} from "@/lib/session-api";
import {
  DEFAULT_QUIZ_CONFIG,
  buildQuizWSConfig,
  type DeepQuestionFormConfig,
} from "@/lib/quiz-types";
import {
  DEFAULT_VISUALIZE_CONFIG,
  buildVisualizeWSConfig,
  type VisualizeFormConfig,
} from "@/lib/visualize-types";
import {
  buildResearchWSConfig,
  createEmptyResearchConfig,
  validateResearchConfig,
  type DeepResearchFormConfig,
  type OutlineItem,
} from "@/lib/research-types";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { getSubagentSettings } from "@/lib/subagents-api";
import { useLLMOptions } from "@/hooks/useLLMOptions";
import {
  getEnabledOptionalTools,
  invalidateEnabledOptionalToolsCache,
} from "@/lib/tools-settings";
import {
  ALL_TOOLS,
  getChatCapability,
  type ToolName,
} from "@/features/capabilities/presentation";
import { useCapabilityCatalog } from "@/features/capabilities/useCapabilityCatalog";
import { browserStorage } from "@/shared/storage";
import { downloadChatMarkdown } from "@/lib/chat-export";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { isPlaceholderSessionTitle } from "@/lib/session-title";
import type { SpaceMemoryFile } from "@/lib/space-items";
import {
  selectedBooksToPayload,
  type SelectedBookReference,
} from "@/lib/book-references";
import {
  selectedReadingsToPayload,
  type SelectedReadingReference,
} from "@/lib/reading-references";
import {
  normalizeSelectedText,
  textFromDomSelection,
  type SelectionTutorContext,
} from "@/lib/selection-tutor";
import { shouldReturnToChatAfterResearch } from "@/lib/deep-research-report";

const NotebookRecordPicker = dynamic(
  () => import("@/components/notebook/NotebookRecordPicker"),
  {
    ssr: false,
  },
);
const HistorySessionPicker = dynamic(
  () => import("@/components/chat/HistorySessionPicker"),
  {
    ssr: false,
  },
);
const MyAgentsPicker = dynamic(
  () => import("@/components/chat/MyAgentsPicker"),
  {
    ssr: false,
  },
);
const QuestionBankPicker = dynamic(
  () => import("@/components/chat/QuestionBankPicker"),
  {
    ssr: false,
  },
);
const MemoryPicker = dynamic(() => import("@/components/chat/MemoryPicker"), {
  ssr: false,
});
const BookReferencePicker = dynamic(
  () => import("@/components/chat/BookReferencePicker"),
  {
    ssr: false,
  },
);
const ReadingReferencePicker = dynamic(
  () => import("@/components/chat/ReadingReferencePicker"),
  {
    ssr: false,
  },
);
const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  {
    ssr: false,
  },
);
// Activity-panel config card hosts the capability-specific form (Quiz /
// Animator / Visualize / Research). Lazy-loaded so capabilities that
// don't need a form (Chat / Solve) don't ship the form JS.
const CapabilityConfigCard = dynamic(
  () => import("@/components/chat/home/CapabilityConfigCard"),
  {
    ssr: false,
  },
);
const QuizConfigPanel = dynamic(
  () => import("@/components/quiz/QuizConfigPanel"),
  { ssr: false },
);
const VisualizeConfigPanel = dynamic(
  () => import("@/components/visualize/VisualizeConfigPanel"),
  {
    ssr: false,
  },
);
const ResearchConfigPanel = dynamic(
  () => import("@/components/research/ResearchConfigPanel"),
  {
    ssr: false,
  },
);

/* ------------------------------------------------------------------ */
/*  Type & data definitions                                           */
/* ------------------------------------------------------------------ */

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
  metadata?: {
    /** Connected-source kind, e.g. "obsidian" | "subagent". */
    type?: string;
    /** Backend of a connected subagent: "claude_code" | "codex" | "partner". */
    agent_kind?: string;
    rag_provider?: string;
  };
  statistics?: {
    rag_provider?: string;
  };
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

/**
 * Read the context-window measurement a finished turn attached to its
 * `result` event. Scanned newest-first because one turn can emit several
 * results (a consulted subagent emits its own) and only the chat loop's
 * closing one carries the budget; older backends emit none at all, and the
 * measurement is allowed to degrade to "absent" rather than fail a turn.
 */
function readContextBudget(
  events: StreamEvent[] | undefined,
): ContextBudget | null {
  if (!events) return null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.type !== "result") continue;
    const meta = ev.metadata?.metadata as Record<string, unknown> | undefined;
    const budget = meta?.context_budget as ContextBudget | undefined;
    if (
      budget &&
      typeof budget.window === "number" &&
      typeof budget.used_tokens === "number" &&
      Array.isArray(budget.segments)
    ) {
      return budget;
    }
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Chat page                                                         */
/* ------------------------------------------------------------------ */

export default function ChatWorkspace() {
  const { router, sessionId: sessionIdParam } = useChatRouteSession();
  const { t } = useTranslation();
  const {
    capabilities,
    visibleCapabilities,
    isLoading: isCapabilityCatalogLoading,
  } = useCapabilityCatalog();
  const { setActiveSessionId, language: appLanguage } = useAppShell();

  const {
    state,
    setTools,
    setCapability,
    setKBs,
    setLLMSelection,
    setPersonaSelection,
    sendMessage,
    cancelStreamingTurn,
    submitUserReply,
    regenerateLastMessage,
    deleteTurn,
    editMessage,
    switchBranch,
    newSession,
    loadSession,
    showCachedSession,
    loadMessageTrace,
    releaseMessageTrace,
    renameSessionTitle,
    setCourseId,
  } = useChatStateAdapter();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBasesLoaded, setKnowledgeBasesLoaded] = useState(false);
  const availableKbNames = useMemo(
    () => new Set(knowledgeBases.map((kb) => kb.name)),
    [knowledgeBases],
  );
  // A connected agent to preselect once it loads, from `?agent=<name>` on the
  // URL (the partner list page links here to drop straight into a chat with a
  // partner). Captured once at first client render — the URL is rewritten to
  // `/chat/<sessionId>` as soon as the new session is created, dropping the
  // query — so we can't read it later from the live search params.
  const pendingAgentRef = useRef<string | null | undefined>(undefined);
  if (pendingAgentRef.current === undefined) {
    pendingAgentRef.current =
      typeof window === "undefined"
        ? null
        : new URLSearchParams(window.location.search).get("agent");
  }
  // Which course this conversation belongs to. Lives in chat state (not a
  // one-shot ref) because the binding is now visible and changeable in the
  // composer for the whole life of the conversation, not only on the turn that
  // created it: a `?course=` link seeds it, the pill edits it, and the server's
  // session preferences are the truth whenever an existing session is opened.
  const courseId = state.courseId;
  const [courses, setCourses] = useState<StudyCourse[]>([]);
  // The course this conversation was *launched* into, and whether its defaults
  // have been applied. A course declares the mode and persona its conversations
  // start in; applying them to an existing transcript would silently rewrite
  // how an ongoing conversation behaves, so they only ever seed a fresh one.
  const launchCourseRef = useRef<string | null>(null);
  const launchIntentAppliedRef = useRef(false);
  const courseDefaultsAppliedRef = useRef(false);
  useEffect(() => {
    void listCourses()
      .then(setCourses)
      // No courses to offer is a legitimate answer, and the pill degrades to
      // an empty menu with a link to make one.
      .catch(() => setCourses([]));
  }, []);
  const agentPreselectDoneRef = useRef(false);
  const {
    options: llmOptions,
    activeDefault: activeLLMDefault,
    loading: llmOptionsLoading,
    error: llmOptionsError,
    refresh: refreshLLMOptions,
  } = useLLMOptions();
  // User-toggleable tools the user has enabled in /settings#tools. This is
  // the single source of truth for which optional tools the chat agent may
  // use; the chat composer no longer exposes a picker.
  const [userEnabledTools, setUserEnabledTools] = useState<string[] | null>(
    null,
  );
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const attachmentLimits = useAttachmentLimits();
  const [dragging, setDragging] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [previewSource, setPreviewSource] = useState<FilePreviewSource | null>(
    null,
  );
  // Right-side panels — Activity (floating cards) and Viewer (full sidebar
  // with tabs for file previews + web pages). Each independently togglable
  // and persisted across reloads.
  //
  // We initialise both to `false` so the SSR-rendered HTML matches the
  // first client render exactly (no hydration mismatch). The persisted
  // preference is then applied in a post-mount effect below.
  // Single right-side panel: the Activity/Viewer. Its home view is the
  // session activity; files and web pages open as tabs alongside it.
  const [viewerPanelOpen, setViewerPanelOpen] = useState(false);
  const [selectionTutorPrompt, setSelectionTutorPrompt] = useState<{
    text: string;
    sourceMessageId: number;
    sourceMessageText: string;
    sourceMessageRole: SelectionTutorContext["sourceMessageRole"];
    left: number;
    top: number;
  } | null>(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (browserStorage.readRaw("local", "dt:chat:viewer-panel") === "1") {
      setViewerPanelOpen(true);
    }
  }, []);
  const setViewerOpen = useCallback((next: boolean) => {
    setViewerPanelOpen(next);
    if (typeof window !== "undefined") {
      browserStorage.writeRaw(
        "local",
        "dt:chat:viewer-panel",
        next ? "1" : "0",
      );
    }
  }, []);
  const toggleViewerPanel = useCallback(() => {
    setViewerPanelOpen((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        browserStorage.writeRaw(
          "local",
          "dt:chat:viewer-panel",
          next ? "1" : "0",
        );
      }
      return next;
    });
  }, []);
  /**
   * Force the panel open on its Activity home. Used by the send-gate when the
   * user tries to send while the active capability still needs its config
   * confirmed — the config card lives on the Activity home, so we open the
   * panel and switch to it. Also used by the capability-switch auto-open
   * effect below.
   */
  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null);
  const ensureActivityPanelOpen = useCallback(() => {
    setViewerOpen(true);
    viewerPanelRef.current?.focusActivityHome();
  }, [setViewerOpen]);
  const attachmentErrorTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const [quizConfig, setQuizConfig] = useState<DeepQuestionFormConfig>({
    ...DEFAULT_QUIZ_CONFIG,
  });
  const [quizValidationErrors, setQuizValidationErrors] = useState<string[]>(
    [],
  );
  const [quizPdf, setQuizPdf] = useState<File | null>(null);
  const [visualizeConfig, setVisualizeConfig] = useState<VisualizeFormConfig>({
    ...DEFAULT_VISUALIZE_CONFIG,
  });
  const [researchConfig, setResearchConfig] = useState<DeepResearchFormConfig>(
    createEmptyResearchConfig(),
  );
  // Capability-config confirmation gate.
  //
  // For capabilities that need explicit configuration (Quiz, Visualize,
  // Research), the user must click *Confirm* in the right-side Activity
  // panel before sending. Any subsequent edit to the underlying config
  // invalidates the confirmation, so the user re-confirms once they've
  // adjusted settings. Capability switches also reset this flag.
  const [capabilityConfigConfirmed, setCapabilityConfigConfirmed] =
    useState(false);
  // Per-session persistence of the capability-config form. The form lives
  // in local React state, so anything that remounts the page (browser
  // back/forward to /chat/<id>, URL-driven session swap, etc.) would
  // otherwise wipe a confirmed-and-already-sent setup back to defaults.
  // Storing the form by sessionId in localStorage keeps the selections —
  // and the Confirmed badge — stable for the rest of the session.
  const capabilityConfigStorageKey = useMemo(() => {
    const sid = state.sessionId || sessionIdParam || "";
    return sid ? `dt:chat:capability-config:${sid}` : null;
  }, [state.sessionId, sessionIdParam]);
  const lastHydratedConfigKeyRef = useRef<string | null>(null);
  // Hydrate the form configs on first encounter of each session id, so
  // the user's prior selections come back when they return to a session.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!capabilityConfigStorageKey) return;
    if (lastHydratedConfigKeyRef.current === capabilityConfigStorageKey) return;
    lastHydratedConfigKeyRef.current = capabilityConfigStorageKey;
    const raw = browserStorage.readRaw("local", capabilityConfigStorageKey);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as {
        quizConfig?: DeepQuestionFormConfig;
        visualizeConfig?: VisualizeFormConfig;
        researchConfig?: DeepResearchFormConfig;
        capabilityConfigConfirmed?: boolean;
      };
      if (parsed.quizConfig) setQuizConfig(parsed.quizConfig);
      if (parsed.visualizeConfig) setVisualizeConfig(parsed.visualizeConfig);
      if (parsed.researchConfig) setResearchConfig(parsed.researchConfig);
      if (typeof parsed.capabilityConfigConfirmed === "boolean") {
        setCapabilityConfigConfirmed(parsed.capabilityConfigConfirmed);
      }
    } catch {
      /* corrupted entry — ignore */
    }
  }, [capabilityConfigStorageKey]);
  // Persist on every change. Write is synchronous and small, and
  // localStorage already de-dupes identical writes at the browser level.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!capabilityConfigStorageKey) return;
    browserStorage.writeRaw(
      "local",
      capabilityConfigStorageKey,
      JSON.stringify({
        quizConfig,
        visualizeConfig,
        researchConfig,
        capabilityConfigConfirmed,
      }),
    );
  }, [
    capabilityConfigStorageKey,
    quizConfig,
    visualizeConfig,
    researchConfig,
    capabilityConfigConfirmed,
  ]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [showBookPicker, setShowBookPicker] = useState(false);
  const [showReadingPicker, setShowReadingPicker] = useState(false);
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showAgentsPicker, setShowAgentsPicker] = useState(false);
  const [showQuestionBankPicker, setShowQuestionBankPicker] = useState(false);
  // Session persona selector (toolbar chip / `/persona` / @space entry all
  // open the same dropdown). The selection itself lives in the unified chat
  // context (state.personaSelection) so it follows the session.
  const [personaSelectorOpen, setPersonaSelectorOpen] = useState(false);
  const [showMemoryPicker, setShowMemoryPicker] = useState(false);
  const [spaceMenuOpen, setSpaceMenuOpen] = useState(false);
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<
    SelectedRecord[]
  >([]);
  const [selectedBookReferences, setSelectedBookReferences] = useState<
    SelectedBookReference[]
  >([]);
  const [selectedReadingReferences, setSelectedReadingReferences] = useState<
    SelectedReadingReference[]
  >([]);
  const [selectedHistorySessions, setSelectedHistorySessions] = useState<
    SelectedHistorySession[]
  >([]);
  // Imported-agent conversation references. Same shape as history sessions —
  // they fold into the same history_references payload (see below), so the
  // backend treats them identically; the separate state only keeps the
  // composer's "My Agents" group distinct from "Chat History".
  const [selectedAgentSessions, setSelectedAgentSessions] = useState<
    SelectedHistorySession[]
  >([]);
  const [selectedQuestionEntries, setSelectedQuestionEntries] = useState<
    SelectedQuestionEntry[]
  >([]);
  const [selectedMemoryFiles, setSelectedMemoryFiles] = useState<
    SpaceMemoryFile[]
  >([]);
  const dragCounter = useRef(0);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const spaceMenuRef = useRef<HTMLDivElement>(null);
  const spaceBtnRef = useRef<HTMLButtonElement>(null);
  const initialLoadRef = useRef(false);
  // Session-loading overlay: shown while navigating from chat-history →
  // session detail. Holds an AbortController so the user can cancel.
  const [sessionLoading, setSessionLoading] = useState(false);
  // A load that ended without a session: terminal, and retryable. Kept
  // separate from `sessionLoading` so the overlay can tell "still
  // arriving" apart from "never arrived".
  const [sessionLoadFailed, setSessionLoadFailed] = useState(false);
  const loadAbortRef = useRef<AbortController | null>(null);
  // Bridge ref: ``ChatComposer`` writes a prefill function into this on
  // mount; ``ChatMessageList`` reads it via ``handlePrefillComposer`` so an
  // ``AskUserOptions`` chip click can drop text into the composer textarea.
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
  const handlePrefillComposer = useCallback((text: string) => {
    prefillInputRef.current?.(text);
  }, []);

  // A message handed over by another page (Settings' "set up with DeepTutor"
  // button). Prefilled rather than sent: the user reads what will be asked and
  // presses enter themselves. Consumed once, so a refresh does not retype it.
  //
  // Retried on a short bounded schedule rather than fired once: the composer
  // installs its prefill bridge from its own effect, and it is not mounted at
  // all while a session is still loading. A single attempt would land on a null
  // ref and drop the message silently — the user arrives from Settings at an
  // empty box with no idea the button did anything.
  useEffect(() => {
    // Two producers: the Settings hub writes the unscoped slot, and a Course
    // Study hand-off to chat writes the "chat" one.
    const pending = consumePendingPrompt() || consumePendingPrompt("chat");
    if (!pending) return;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const attempt = () => {
      if (prefillInputRef.current) {
        handlePrefillComposer(pending);
        return;
      }
      if (attempts++ >= 20) return; // ~2s, then give up quietly
      timer = setTimeout(attempt, 100);
    };
    timer = setTimeout(attempt, 0);
    return () => clearTimeout(timer);
  }, [handlePrefillComposer]);

  // A clickable node inside an inlined visualization SVG (data-prompt) — and the
  // html widget's sendPrompt bridge — dispatch this window event; mirror it into
  // the composer as a prefilled follow-up (user confirms before sending).
  useEffect(() => {
    const onVizPrompt = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (typeof text === "string" && text) handlePrefillComposer(text);
    };
    window.addEventListener("dt:visualize-prompt", onVizPrompt);
    return () => window.removeEventListener("dt:visualize-prompt", onVizPrompt);
  }, [handlePrefillComposer]);

  useEffect(() => {
    const onWatchingAsk = (event: Event) => {
      const detail = (
        event as CustomEvent<{ timeSeconds?: number; text?: string }>
      ).detail;
      const text = (detail?.text || "").trim();
      if (!text) return;
      const total = Math.max(0, Math.floor(Number(detail?.timeSeconds) || 0));
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const seconds = total % 60;
      const timestamp = hours
        ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
        : `${minutes}:${String(seconds).padStart(2, "0")}`;
      handlePrefillComposer(
        `> [${timestamp}] ${text}\n\n${t("Explain this part of the video")}: `,
      );
    };
    window.addEventListener(WATCHING_ASK_EVENT, onWatchingAsk);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, onWatchingAsk);
  }, [handlePrefillComposer, t]);

  const activeCap = useMemo(
    () =>
      capabilities.find(
        (capability) => capability.value === (state.activeCapability || ""),
      ) ?? getChatCapability(state.activeCapability),
    [capabilities, state.activeCapability],
  );
  const isQuizMode = activeCap.value === "deep_question";
  const isVisualizeMode = activeCap.value === "visualize";
  const isResearchMode = activeCap.value === "deep_research";
  const isWatchingMode = activeCap.value === "immersive_watching";
  const capabilityNeedsConfig = isQuizMode || isVisualizeMode || isResearchMode;
  const returnedResearchTurnRef = useRef<string | null>(null);

  // Deep Research is a one-shot workflow: once its confirmed-outline turn
  // reaches a terminal event, ordinary composer messages should discuss the
  // report in chat context. Keeping the mode selected caused follow-ups such
  // as "why did this stop?" to become brand-new research outlines. The Retry
  // button still submits the preserved outline explicitly as deep_research.
  useEffect(() => {
    if (state.isStreaming || state.activeCapability !== "deep_research") return;
    const latestAssistant = [...state.messages]
      .reverse()
      .find((message) => message.role === "assistant");
    if (
      !latestAssistant ||
      !shouldReturnToChatAfterResearch(latestAssistant.events)
    ) {
      return;
    }
    const terminal = [...(latestAssistant.events ?? [])]
      .reverse()
      .find((event) => event.type === "done");
    const turnKey = String(terminal?.turn_id || latestAssistant.id || "");
    if (!turnKey || returnedResearchTurnRef.current === turnKey) return;
    returnedResearchTurnRef.current = turnKey;
    setCapability(null);
    setCapabilityConfigConfirmed(false);
  }, [
    setCapability,
    state.activeCapability,
    state.isStreaming,
    state.messages,
  ]);

  // Edit-invalidates-confirm wrappers — flipping any field after the user
  // hit *Confirm* should restore the gate so they re-confirm intentionally.
  // `useCallback` keeps identities stable so the memoized ChatComposer /
  // CapabilityConfigCard don't churn on every keystroke.
  const handleChangeQuizConfig = useCallback((next: DeepQuestionFormConfig) => {
    setQuizConfig(next);
    setQuizValidationErrors([]);
    setCapabilityConfigConfirmed(false);
  }, []);
  const handleUploadQuizPdf = useCallback((file: File | null) => {
    setQuizPdf(file);
    setCapabilityConfigConfirmed(false);
  }, []);
  const handleChangeVisualizeConfig = useCallback(
    (next: VisualizeFormConfig) => {
      setVisualizeConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
  const handleChangeResearchConfig = useCallback(
    (next: DeepResearchFormConfig) => {
      setResearchConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
  const handleConfirmCapabilityConfig = useCallback(() => {
    setCapabilityConfigConfirmed(true);
  }, []);

  /**
   * Auto-open the right-side Activity panel when the user switches into a
   * capability that requires manual configuration (Quiz / Animator /
   * Visualize / Research). We only fire on the transition from "doesn't
   * need config" → "needs config" so we don't fight the user if they
   * close the panel themselves while still in a config-needing mode.
   *
   * Tracking via a ref (instead of deps) avoids re-firing whenever the
   * panel toggles — the open-state flip should be one-shot per cap
   * transition.
   */
  const lastCapabilityNeedsConfigRef = useRef(capabilityNeedsConfig);
  useEffect(() => {
    const prev = lastCapabilityNeedsConfigRef.current;
    lastCapabilityNeedsConfigRef.current = capabilityNeedsConfig;
    if (!prev && capabilityNeedsConfig) {
      ensureActivityPanelOpen();
    }
  }, [capabilityNeedsConfig, ensureActivityPanelOpen]);
  // Adopt UI preferences the assistant changed mid-conversation: the browser
  // otherwise keeps serving its own cached language/theme and the user is told
  // "done" while nothing visibly changes.
  useSetupSync(state.messages);
  const hasMessages = state.messages.length > 0;
  // A line the user might type next, written by the task model against the
  // conversation's own tail — general prediction, not a question to ask,
  // unlike the mastery/reading composers' hint. Empty conversations already
  // get their own richer suggestions from StarterSuggestions below, so this
  // only ever runs once there is something to continue. Cleared on session
  // switch so a prior chat's guess never lingers as this one's placeholder.
  const [askHint, setAskHint] = useState("");
  useEffect(() => {
    setAskHint("");
  }, [state.sessionId]);
  useEffect(() => {
    if (state.isStreaming || !hasMessages || !state.sessionId) return;
    let cancelled = false;
    void fetchSessionAskHint(state.sessionId).then((hint) => {
      if (!cancelled) setAskHint(hint);
    });
    return () => {
      cancelled = true;
    };
  }, [state.isStreaming, hasMessages, state.sessionId, state.messages.length]);
  // Time-of-day greeting: seeded once on mount from the user's local clock so
  // the heading stays stable while they're on the page. State (not useMemo)
  // because the random pick would otherwise mismatch SSR ↔ client hydration.
  const [welcomeGreeting, setWelcomeGreeting] = useState<string>(
    "What would you like to learn?",
  );
  useEffect(() => {
    const hour = new Date().getHours();
    let bucket: string[];
    if (hour >= 5 && hour < 12) {
      bucket = [
        "Good morning.",
        "Morning — let's learn something.",
        "What would you like to learn?",
      ];
    } else if (hour >= 12 && hour < 17) {
      bucket = [
        "Good afternoon.",
        "Afternoon — what's on your mind?",
        "What would you like to learn?",
      ];
    } else if (hour >= 17 && hour < 22) {
      bucket = [
        "Good evening.",
        "Evening — what shall we explore?",
        "What would you like to learn?",
      ];
    } else {
      bucket = [
        "It's late today.",
        "Burning the midnight oil?",
        "What would you like to learn?",
      ];
    }
    setWelcomeGreeting(bucket[Math.floor(Math.random() * bucket.length)]);
  }, []);
  const firstUserTitle = useMemo(
    () =>
      state.messages
        .find((msg) => msg.role === "user")
        ?.content.trim()
        .replace(/\s+/g, " ")
        .slice(0, 80) || "",
    [state.messages],
  );
  const persistedSessionTitle = state.sessionTitle.trim();
  const displaySessionTitle = isPlaceholderSessionTitle(persistedSessionTitle)
    ? firstUserTitle || t("New chat")
    : persistedSessionTitle;
  const canRenameSession = Boolean(state.sessionId);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const skipTitleCommitRef = useRef(false);
  const [sessionTitleDraft, setSessionTitleDraft] =
    useState(displaySessionTitle);
  const [sessionTitleEditing, setSessionTitleEditing] = useState(false);
  const [sessionTitleSaving, setSessionTitleSaving] = useState(false);
  const [sessionTitleError, setSessionTitleError] = useState<string | null>(
    null,
  );
  useEffect(() => {
    if (sessionTitleEditing) return;
    setSessionTitleDraft(displaySessionTitle);
  }, [displaySessionTitle, sessionTitleEditing]);
  useEffect(() => {
    if (!sessionTitleEditing) return;
    window.requestAnimationFrame(() => {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    });
  }, [sessionTitleEditing]);
  const startSessionTitleEdit = useCallback(() => {
    if (!canRenameSession) return;
    skipTitleCommitRef.current = false;
    setSessionTitleError(null);
    setSessionTitleDraft(displaySessionTitle);
    setSessionTitleEditing(true);
  }, [canRenameSession, displaySessionTitle]);
  const cancelSessionTitleEdit = useCallback(() => {
    skipTitleCommitRef.current = true;
    setSessionTitleDraft(displaySessionTitle);
    setSessionTitleError(null);
    setSessionTitleEditing(false);
  }, [displaySessionTitle]);
  const commitSessionTitleEdit = useCallback(async () => {
    if (skipTitleCommitRef.current) {
      skipTitleCommitRef.current = false;
      return;
    }
    const next = sessionTitleDraft.trim();
    if (!next) {
      setSessionTitleDraft(displaySessionTitle);
      setSessionTitleEditing(false);
      return;
    }
    if (!canRenameSession || next === persistedSessionTitle) {
      setSessionTitleDraft(next || displaySessionTitle);
      setSessionTitleEditing(false);
      return;
    }
    setSessionTitleSaving(true);
    setSessionTitleError(null);
    try {
      await renameSessionTitle(next);
      setSessionTitleEditing(false);
    } catch (error) {
      console.error("Failed to rename session:", error);
      setSessionTitleError(t("Rename failed"));
      titleInputRef.current?.focus();
    } finally {
      setSessionTitleSaving(false);
    }
  }, [
    canRenameSession,
    displaySessionTitle,
    persistedSessionTitle,
    renameSessionTitle,
    sessionTitleDraft,
    t,
  ]);
  const handleSessionTitleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void commitSessionTitleEdit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelSessionTitleEdit();
      }
    },
    [cancelSessionTitleEdit, commitSessionTitleEdit],
  );
  const { ref: composerRef, height: composerHeight } =
    useMeasuredHeight<HTMLDivElement>();
  const researchValidation = useMemo(
    () => validateResearchConfig(researchConfig),
    [researchConfig],
  );
  const notebookReferenceGroups = useMemo(() => {
    const groups = new Map<string, { notebookName: string; count: number }>();
    selectedNotebookRecords.forEach((record) => {
      const existing = groups.get(record.notebookId);
      if (existing) {
        existing.count += 1;
      } else {
        groups.set(record.notebookId, {
          notebookName: record.notebookName,
          count: 1,
        });
      }
    });
    return Array.from(groups.entries()).map(([notebookId, value]) => ({
      notebookId,
      ...value,
    }));
  }, [selectedNotebookRecords]);
  const notebookReferencesPayload = useMemo(() => {
    const grouped = new Map<string, string[]>();
    selectedNotebookRecords.forEach((record) => {
      const current = grouped.get(record.notebookId) || [];
      current.push(record.id);
      grouped.set(record.notebookId, current);
    });
    return Array.from(grouped.entries()).map(([notebook_id, record_ids]) => ({
      notebook_id,
      record_ids,
    }));
  }, [selectedNotebookRecords]);
  const bookReferencesPayload = useMemo(
    () => selectedBooksToPayload(selectedBookReferences),
    [selectedBookReferences],
  );
  const readingReferencesPayload = useMemo(
    () => selectedReadingsToPayload(selectedReadingReferences),
    [selectedReadingReferences],
  );
  // Chat-history and imported-agent references are both just session ids and
  // share one backend field. Merge + de-dupe them here.
  const historyReferencesPayload = useMemo(
    () =>
      Array.from(
        new Set([
          ...selectedHistorySessions.map((session) => session.sessionId),
          ...selectedAgentSessions.map((session) => session.sessionId),
        ]),
      ),
    [selectedHistorySessions, selectedAgentSessions],
  );
  const questionNotebookReferencesPayload = useMemo(
    () => selectedQuestionEntries.map((entry) => entry.id),
    [selectedQuestionEntries],
  );
  const memoryReferencesPayload = useMemo(
    () => [...selectedMemoryFiles],
    [selectedMemoryFiles],
  );
  const { modalMessages: chatSaveMessages, payload: chatSavePayload } =
    useMemo(
      () =>
        buildConversationNotebookSave(state.messages, {
          source: "chat",
          fallbackTitle: "Chat Session",
          activeCapability: state.activeCapability,
          language: state.language,
          sessionId: state.sessionId,
        }),
      [
        state.activeCapability,
        state.language,
        state.messages,
        state.sessionId,
      ],
    );
  const lastMessage = state.messages[state.messages.length - 1];
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll: handleMessagesScroll,
  } = useChatAutoScroll({
    hasMessages,
    isStreaming: state.isStreaming,
    composerHeight,
    messageCount: state.messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  });

  // ─── Turn navigator ───
  // One tick per question the user asked, rendered in the transcript's
  // left gutter (see ``TurnNavigator``). The outline is derived from the
  // same visible-path walk the message list uses, so switching an edit
  // branch reshapes both together.
  const chatOutline = useMemo(
    () => buildChatOutline(state.messages, state.selectedBranches),
    [state.messages, state.selectedBranches],
  );
  /** Bring a question back on screen and mark where the user landed. */
  const jumpToTurn = useCallback(
    (key: string) => {
      const container = messagesContainerRef.current;
      // 56 px clears the scrollport's top fade so the bubble lands fully
      // opaque rather than half-dissolved under the mask.
      if (scrollToChatTurn(container, key, { topOffset: 56, flash: true })) {
        // Release the streaming pin: otherwise the next content delta snaps
        // the reader straight back to the bottom they just left.
        shouldAutoScrollRef.current = false;
      }
    },
    [messagesContainerRef, shouldAutoScrollRef],
  );
  /** Leave history and start following the live end of the turn again. */
  const resumeFollowingLatest = useCallback(() => {
    shouldAutoScrollRef.current = true;
    scrollToBottom("instant");
  }, [scrollToBottom, shouldAutoScrollRef]);

  /* A card waiting on the user is the one thing that MUST be on screen: the
     turn cannot continue until they act on it. Reading the question that
     precedes it normally scrolls up, which releases the streaming pin — so a
     quiz card would appear below the fold, under the composer, and the
     conversation looked stalled. Re-arm the pin and land on the card. */
  const awaitingUserReply = hasPendingAskUser(lastMessage?.events);
  // Read inside ``handleSend`` without adding a dependency that would rebuild
  // the callback (and so the composer) on every streamed event.
  const awaitingUserReplyRef = useRef(awaitingUserReply);
  awaitingUserReplyRef.current = awaitingUserReply;
  useEffect(() => {
    if (!awaitingUserReply) return;
    shouldAutoScrollRef.current = true;
    // One frame later: the card has to be laid out before the bottom it
    // defines exists.
    const frame = requestAnimationFrame(() => scrollToBottom("instant"));
    return () => cancelAnimationFrame(frame);
  }, [awaitingUserReply, scrollToBottom, shouldAutoScrollRef]);

  const copyAssistantMessage = useCallback(async (content: string) => {
    if (!content.trim()) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch (error) {
      console.error("Failed to copy assistant message:", error);
    }
  }, []);
  /* ---- URL-driven session loading ---- */

  const navigateToHome = useCallback(() => {
    router.replace("/chat", { scroll: false });
  }, [router]);

  /** Abort in-flight load + navigate home. */
  const cancelSessionLoad = useCallback(() => {
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    setSessionLoading(false);
    setSessionLoadFailed(false);
    navigateToHome();
  }, [navigateToHome]);

  /**
   * Shared helper: kick off a load. The user can cancel via the ✕ button.
   *
   * A session we already hold in memory is painted right away and refreshed
   * in the background — switching back to a conversation read earlier in this
   * visit costs nothing, and the overlay is reserved for the case where we
   * genuinely have nothing to show.
   *
   * The wait is bounded. A fetch that never settles used to leave the overlay
   * spinning forever with no way out but abandoning the conversation, and a
   * fetch that *failed* used to replace the URL with /chat — dropping the
   * session id, so a transient error read as "my history is gone". Both now
   * end in the same terminal, retryable state with the id still in the URL.
   */
  const startSessionLoad = useCallback(
    (sid: string) => {
      loadAbortRef.current?.abort();
      const ctrl = new AbortController();
      loadAbortRef.current = ctrl;
      const cached = showCachedSession(sid);
      setSessionLoading(!cached);
      setSessionLoadFailed(false);

      // Aborting is how the timeout stops waiting, so it has to be
      // distinguishable from the user's ✕ and from a newer load taking over:
      // those two own the resulting state, a timeout does not.
      let timedOut = false;
      const timeout = setTimeout(() => {
        timedOut = true;
        ctrl.abort();
      }, SESSION_LOAD_TIMEOUT_MS);

      void loadSession(sid, { signal: ctrl.signal, revalidate: cached })
        .then(() => {
          clearTimeout(timeout);
          if (!ctrl.signal.aborted) {
            loadAbortRef.current = null;
            setSessionLoading(false);
            // Settle at the bottom once the transcript is really laid out.
            // The layout-effect pin runs as the messages first render, when
            // lazily-loaded images (ChatMessages `loading="lazy"`) and the
            // `next/dynamic` capability viewers have not contributed their
            // heights yet, so its `scrollHeight` is short and the viewport
            // stops above the true bottom. One frame later those are in.
            //
            // Only on a cold open. A cached session is already painted at
            // the bottom and this resolves after a background revalidate —
            // re-arming there would yank a reader who had scrolled up.
            if (!cached) {
              shouldAutoScrollRef.current = true;
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                  // A newer session may have superseded this one while the
                  // two frames elapsed; that load owns the viewport now.
                  if (!ctrl.signal.aborted) scrollToBottom("instant");
                });
              });
            }
          }
        })
        .catch(() => {
          clearTimeout(timeout);
          const surface = shouldSurfaceLoadFailure({
            aborted: ctrl.signal.aborted,
            timedOut,
            cached,
          });
          // A newer load (or the user's ✕) owns the state from here, and a
          // failed background refresh leaves the cached copy on screen.
          if (!surface) return;
          loadAbortRef.current = null;
          setSessionLoading(false);
          setSessionLoadFailed(true);
        });
    },
    [loadSession, showCachedSession, scrollToBottom, shouldAutoScrollRef],
  );

  const retrySessionLoad = useCallback(() => {
    if (sessionIdParam) startSessionLoad(sessionIdParam);
  }, [sessionIdParam, startSessionLoad]);

  // Initial mount — load the session from the URL.
  // Uses a ref-based flag so Strict Mode double-mount doesn't break the flow:
  // when React tears down + re-mounts in dev, we reset initialLoadRef in
  // cleanup so the second mount restarts the load cleanly. The abort is
  // deliberately OMITTED from cleanup — cancelSessionLoad handles
  // user-initiated cancellation.
  useEffect(() => {
    if (initialLoadRef.current) return;
    initialLoadRef.current = true;
    if (sessionIdParam) {
      startSessionLoad(sessionIdParam);
    } else {
      newSession();
    }
    return () => {
      initialLoadRef.current = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // When URL param changes (sidebar navigation), load the corresponding session
  const prevSessionIdParam = useRef(sessionIdParam);
  useEffect(() => {
    if (sessionIdParam === prevSessionIdParam.current) return;
    prevSessionIdParam.current = sessionIdParam;
    // Abort any in-flight session load from the previous param
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    if (sessionIdParam) {
      if (sessionIdParam === state.sessionId) {
        setSessionLoading(false);
        setSessionLoadFailed(false);
        return;
      }
      startSessionLoad(sessionIdParam);
    } else {
      newSession();
      setSessionLoading(false);
      setSessionLoadFailed(false);
    }
  }, [sessionIdParam, startSessionLoad, newSession, state.sessionId]);

  // When a new session_id is assigned by the server, update the URL
  useEffect(() => {
    if (state.sessionId && !sessionIdParam) {
      router.replace(`/chat/${state.sessionId}`, { scroll: false });
    }
  }, [state.sessionId, sessionIdParam, router]);

  useEffect(() => {
    setActiveSessionId(state.sessionId || sessionIdParam || null);
  }, [state.sessionId, sessionIdParam, setActiveSessionId]);

  const refreshKnowledgeBases = useCallback(
    async (options?: { force?: boolean }) => {
      try {
        const list = await listKnowledgeBases({ force: options?.force });
        setKnowledgeBases(list);
        setKnowledgeBasesLoaded(true);
      } catch {
        setKnowledgeBasesLoaded(false);
        setKnowledgeBases([]);
      }
    },
    [],
  );

  /* Load KBs.
   *
   * Switching sessions remounts this page (the session id is a route
   * segment), so these mount-time loads run again on every switch. They read
   * through the shared client cache rather than forcing a refetch: forcing
   * would put a handful of session-independent requests on the wire in
   * parallel with the session fetch itself, and they'd compete for the same
   * six connections — that, not the conversation's length, is what used to
   * make opening a chat feel slow. The focus/visibility listener below is
   * what keeps these values fresh. */
  useEffect(() => {
    void refreshKnowledgeBases();
  }, [refreshKnowledgeBases]);

  // A physical KB delete does not cascade into persisted session preferences.
  // Reconcile only after a successful fetch: an empty result then means every
  // KB was deleted, while a failed request must keep the existing selection.
  useEffect(() => {
    if (!knowledgeBasesLoaded) return;
    const selected = state.knowledgeBases;
    const pruned = selected.filter((name) => availableKbNames.has(name));
    if (pruned.length !== selected.length) setKBs(pruned);
  }, [availableKbNames, knowledgeBasesLoaded, state.knowledgeBases, setKBs]);

  const refreshUserEnabledTools = useCallback(
    async (options?: { force?: boolean }) => {
      try {
        const list = await getEnabledOptionalTools({ force: options?.force });
        setUserEnabledTools(list);
      } catch {
        setUserEnabledTools([]);
      }
    },
    [],
  );

  /* Load user tool prefs */
  useEffect(() => {
    void refreshUserEnabledTools();
  }, [refreshUserEnabledTools]);

  useEffect(() => {
    if (state.llmSelection || !activeLLMDefault) return;
    setLLMSelection(activeLLMDefault);
  }, [activeLLMDefault, setLLMSelection, state.llmSelection]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const refresh = () => {
      void refreshKnowledgeBases({ force: true });
      void refreshLLMOptions({ force: true, background: true });
      // Picks up toggles the user changed in another tab (/settings#tools).
      invalidateEnabledOptionalToolsCache();
      void refreshUserEnabledTools({ force: true });
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [refreshKnowledgeBases, refreshLLMOptions, refreshUserEnabledTools]);

  /* Composer setup requested by the URL that opened this page. Runs once:
     from here on the composer is the user's to change. */
  useEffect(() => {
    if (typeof window === "undefined" || launchIntentAppliedRef.current) return;
    const intent = readChatLaunchIntent(window.location.search);
    const launchCourse = new URLSearchParams(window.location.search)
      .get("course")
      ?.trim();
    if (launchCourse) {
      setCourseId(launchCourse);
      launchCourseRef.current = launchCourse;
    }
    // Capability identity is backend-owned. Do not resolve a deep link against
    // the temporary chat-only fallback while the catalog request is in flight.
    if (intent.capability !== null && isCapabilityCatalogLoading) return;
    launchIntentAppliedRef.current = true;
    if (intent.capability !== null) handleSelectCapability(intent.capability);
    else if (intent.tools.length) {
      const valid = intent.tools.filter((t): t is ToolName =>
        ALL_TOOLS.some((d) => d.name === t),
      );
      if (valid.length) setTools(Array.from(new Set(valid)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCapabilityCatalogLoading]);

  /* What a conversation inherits from the course it opens in: its mode, its
     persona, and its material.

     The server has always been willing to supply these (`_apply_course_defaults`
     in turn_runtime) — but only for a payload that omits the fields, and this
     composer always sends all three, so the branch never ran for anyone using
     the app. Doing it here instead also puts the inheritance where the learner
     can see it: the mode chip and the knowledge-base selection visibly become
     the course's before they type, and stay theirs to override.

     Applied once, and only to a conversation launched into the course with
     nothing said yet: an explicit `?capability=` is the learner being specific
     and outranks the course, and a transcript already underway keeps whatever
     it has been running as. */
  useEffect(() => {
    if (courseDefaultsAppliedRef.current) return;
    const launched = launchCourseRef.current;
    if (!launched || !courses.length || hasMessages) return;
    const course = courses.find((item) => item.id === launched);
    if (!course) return;
    courseDefaultsAppliedRef.current = true;
    const explicitCapability = readChatLaunchIntent(
      window.location.search,
    ).capability;
    if (explicitCapability === null && course.default_capability) {
      handleSelectCapability(course.default_capability);
    }
    if (course.default_persona) setPersonaSelection(course.default_persona);
    // The course's own reading is what a conversation inside it should be able
    // to search. Only seeds an untouched selection — never clears one the
    // learner already made.
    const courseKbs = course.resources
      .filter((resource) => resource.kind === "knowledge_base")
      .map((resource) => resource.ref_id);
    if (courseKbs.length && state.knowledgeBases.length === 0) {
      setKBs(courseKbs);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses, hasMessages]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        capMenuRef.current &&
        !capMenuRef.current.contains(t) &&
        capBtnRef.current &&
        !capBtnRef.current.contains(t)
      )
        setCapMenuOpen(false);
      if (
        spaceMenuRef.current &&
        !spaceMenuRef.current.contains(t) &&
        spaceBtnRef.current &&
        !spaceBtnRef.current.contains(t)
      )
        setSpaceMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Keep state.enabledTools = (user's toggleable set) ∩ (capability's allowed
  // set). Re-runs when the user flips a toggle in /settings#tools or when
  // the active capability changes. The composer no longer owns this — the
  // /settings#tools page is the single switchboard.
  useEffect(() => {
    if (userEnabledTools === null) return;
    const allowed = new Set(activeCap.allowedTools);
    const next = userEnabledTools.filter((tool) =>
      allowed.has(tool as ToolName),
    );
    const current = state.enabledTools;
    const same =
      current.length === next.length &&
      current.every((tool, idx) => tool === next[idx]);
    if (!same) setTools(next);
  }, [activeCap.allowedTools, setTools, state.enabledTools, userEnabledTools]);

  /* ---- handlers ---- */

  /* Changing the course from the composer. An existing conversation is moved
     right away rather than at the next turn: the sidebar groups by this, so a
     move the learner made but never "confirmed" by typing would look like it
     did not take. A conversation with no session yet has nothing to write to —
     its binding rides along with the first turn's `_course_id`. */
  const handleSelectCourse = useCallback(
    (nextCourseId: string) => {
      setCourseId(nextCourseId);
      const sid = state.sessionId;
      if (!sid) return;
      void updateSessionOrganization(sid, {
        course_id: nextCourseId,
      }).catch(() => {
        // The turn's own `_course_id` still carries the change, so a failed
        // eager write costs the sidebar an immediate regroup, nothing more.
      });
    },
    [setCourseId, state.sessionId],
  );

  const handleSelectCapability = useCallback(
    (value: string) => {
      const cap =
        capabilities.find((capability) => capability.value === value) ??
        capabilities[0] ??
        getChatCapability("");
      setCapability(cap.value || null);
      // Per-capability tool selection now derives from the user's saved
      // settings (/settings#tools) intersected with the capability's
      // allow-list.
      const baseline =
        userEnabledTools === null ? cap.allowedTools : userEnabledTools;
      const enabledToolsForCap = baseline.filter((tool) =>
        cap.allowedTools.includes(tool as ToolName),
      );
      setTools(enabledToolsForCap);
      // Switching capability invalidates any prior config confirmation —
      // the new capability has its own form that needs explicit confirm.
      setCapabilityConfigConfirmed(false);
      setCapMenuOpen(false);
    },
    [capabilities, setCapability, setTools, userEnabledTools],
  );

  const fileToAttachment = fileToPendingAttachment;

  const showAttachmentError = useCallback((message: string) => {
    setAttachmentError(message);
    if (attachmentErrorTimer.current) {
      clearTimeout(attachmentErrorTimer.current);
    }
    attachmentErrorTimer.current = setTimeout(() => {
      setAttachmentError(null);
      attachmentErrorTimer.current = null;
    }, 4000);
  }, []);

  const filterAndReportFiles = useCallback(
    (files: File[]): File[] => {
      const { accepted, rejected } = selectAttachmentFiles(
        files,
        attachments.reduce((total, item) => total + (item.size ?? 0), 0),
        attachmentLimits,
      );
      if (rejected.length) {
        const first = rejected[0];
        let msg: string;
        if (first.reason === "too_large") {
          msg = t("File too large: {{name}}", { name: first.name });
        } else if (first.reason === "quota") {
          msg = t("Too many files, skipped some");
        } else {
          msg = t("Unsupported file type: {{name}}", { name: first.name });
        }
        showAttachmentError(msg);
      }
      return accepted;
    },
    [attachments, attachmentLimits, showAttachmentError, t],
  );

  const handlePaste = useCallback(
    async (event: React.ClipboardEvent) => {
      const items = Array.from(event.clipboardData.items);
      const files = items
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((f): f is File => f !== null);
      const accepted = filterAndReportFiles(files);
      if (!accepted.length) return;
      event.preventDefault();
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handlePreviewPendingAttachment = useCallback(
    (index: number) => {
      const a = attachments[index];
      if (!a) return;
      setPreviewSource({
        filename: a.filename,
        mimeType: a.mimeType,
        type: a.type,
        base64: a.base64,
        size: a.size,
      });
    },
    [attachments],
  );

  // Fold all messages once per state.messages change to power the
  // SessionActivityPanel on the right (tools, KBs, space refs, attachments).
  const sessionActivity = useMemo(
    () =>
      buildSessionActivity(state.messages, {
        availableKbNames: knowledgeBasesLoaded ? availableKbNames : undefined,
      }),
    [state.messages, availableKbNames, knowledgeBasesLoaded],
  );

  // Context-window readout for the composer chip: the newest turn that was
  // actually measured. Walking newest-first is what keeps the number steady
  // while a new turn streams — the in-flight assistant message has no result
  // event yet, so the walk falls through to the last completed turn and the
  // chip flips exactly once, when the new measurement lands.
  const contextBudget = useMemo(() => {
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      const msg = state.messages[i];
      if (msg.role !== "assistant") continue;
      const budget = readContextBudget(msg.events);
      if (budget) return budget;
    }
    return null;
  }, [state.messages]);

  /**
   * Capability-config card rendered at the bottom of the Activity panel.
   *
   * Returns null for capabilities that don't need explicit configuration
   * (Chat / Solve) — the Activity panel falls back to its standard
   * sections (tools, KBs, space, attachments) plus the empty-state card.
   *
   * For Quiz / Animator / Visualize / Research, we wrap the matching bare
   * ConfigPanel in a `CapabilityConfigCard` that provides the header,
   * Confirm button, and validation-error display. The Confirm gate is
   * wired through `capabilityConfigConfirmed` / `handleConfirmCapabilityConfig`.
   */
  const capabilityConfigSection = useMemo(() => {
    if (!capabilityNeedsConfig) return null;
    if (isQuizMode) {
      return (
        <CapabilityConfigCard
          capability="deep_question"
          confirmed={capabilityConfigConfirmed}
          canConfirm={quizValidationErrors.length === 0}
          validationErrors={quizValidationErrors}
          onConfirm={handleConfirmCapabilityConfig}
        >
          <QuizConfigPanel
            value={quizConfig}
            onChange={handleChangeQuizConfig}
            uploadedPdf={quizPdf}
            onUploadPdf={handleUploadQuizPdf}
          />
        </CapabilityConfigCard>
      );
    }
    if (isVisualizeMode) {
      return (
        <CapabilityConfigCard
          capability="visualize"
          confirmed={capabilityConfigConfirmed}
          canConfirm
          onConfirm={handleConfirmCapabilityConfig}
        >
          <VisualizeConfigPanel
            value={visualizeConfig}
            onChange={handleChangeVisualizeConfig}
          />
        </CapabilityConfigCard>
      );
    }
    // Research: forward validation errors so the user sees what's missing
    // before they hit Confirm. `canConfirm` only flips false when there's
    // an actual error (e.g. mode/depth not selected).
    const researchErrorMessages = Object.values(researchValidation.errors);
    return (
      <CapabilityConfigCard
        capability="deep_research"
        confirmed={capabilityConfigConfirmed}
        canConfirm={researchErrorMessages.length === 0}
        validationErrors={researchErrorMessages}
        onConfirm={handleConfirmCapabilityConfig}
      >
        <ResearchConfigPanel
          value={researchConfig}
          errors={researchValidation.errors}
          onChange={handleChangeResearchConfig}
        />
      </CapabilityConfigCard>
    );
  }, [
    capabilityNeedsConfig,
    isQuizMode,
    isVisualizeMode,
    capabilityConfigConfirmed,
    handleConfirmCapabilityConfig,
    quizConfig,
    quizValidationErrors,
    quizPdf,
    handleChangeQuizConfig,
    handleUploadQuizPdf,
    visualizeConfig,
    handleChangeVisualizeConfig,
    researchConfig,
    researchValidation.errors,
    handleChangeResearchConfig,
  ]);

  // Clicking an attachment (from the Activity home or from a chat message)
  // routes into the panel as a new file tab. It auto-opens and the
  // preference is persisted so a follow-up click feels instant.
  const handlePreviewMessageAttachment = useCallback((a: MessageAttachment) => {
    viewerPanelRef.current?.openFileTab(a);
  }, []);

  // Event-delegated link interception inside the messages container. When
  // the user clicks an http(s) link in an assistant message, we open it as
  // a Viewer tab instead of letting the browser navigate / open a new tab.
  // Cmd/ctrl/shift + click keep their standard meaning (open in browser).
  const handleMessagesClick = useCallback((event: React.MouseEvent) => {
    if (event.defaultPrevented) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    const anchor = target.closest<HTMLAnchorElement>("a[href]");
    if (!anchor) return;
    const href = anchor.getAttribute("href");
    if (!href) return;
    if (!/^https?:\/\//i.test(href)) return;
    event.preventDefault();
    viewerPanelRef.current?.openWebTab(href);
  }, []);

  const handleMessagesSelection = useCallback(() => {
    const container = messagesContainerRef.current;
    const selection = window.getSelection();
    if (
      !container ||
      !selection ||
      selection.isCollapsed ||
      !selection.rangeCount
    ) {
      setSelectionTutorPrompt(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) {
      setSelectionTutorPrompt(null);
      return;
    }
    const text = textFromDomSelection(selection);
    if (text.length < 2) {
      setSelectionTutorPrompt(null);
      return;
    }

    const messageElementForNode = (node: Node | null): HTMLElement | null => {
      const element =
        node instanceof HTMLElement ? node : (node?.parentElement ?? null);
      return element?.closest<HTMLElement>("[data-chat-message-id]") ?? null;
    };
    const anchorMessage = messageElementForNode(selection.anchorNode);
    const focusMessage = messageElementForNode(selection.focusNode);
    if (!anchorMessage || anchorMessage !== focusMessage) {
      setSelectionTutorPrompt(null);
      return;
    }
    const sourceMessageId = Number(anchorMessage.dataset.chatMessageId);
    const sourceMessage = state.messages.find(
      (message) => message.id === sourceMessageId,
    );
    if (!Number.isInteger(sourceMessageId) || !sourceMessage) {
      setSelectionTutorPrompt(null);
      return;
    }

    const rects = range.getClientRects();
    const rect =
      rects.length > 0
        ? rects[rects.length - 1]
        : range.getBoundingClientRect();
    const buttonWidth = 118;
    const buttonHeight = 38;
    const left = Math.max(
      12,
      Math.min(rect.right - buttonWidth, window.innerWidth - buttonWidth - 12),
    );
    const below = rect.bottom + 8;
    const top =
      below + buttonHeight <= window.innerHeight - 12
        ? below
        : Math.max(12, rect.top - buttonHeight - 8);
    setSelectionTutorPrompt({
      text,
      sourceMessageId,
      sourceMessageText: sourceMessage.content,
      sourceMessageRole: sourceMessage.role,
      left,
      top,
    });
  }, [messagesContainerRef, state.messages]);

  const openSelectionTutor = useCallback(() => {
    if (!selectionTutorPrompt) return;
    viewerPanelRef.current?.openSelectionTutorTab(
      {
        selectedText: selectionTutorPrompt.text,
        parentSessionId: state.sessionId,
        sourceMessageId: selectionTutorPrompt.sourceMessageId,
        sourceMessageText: selectionTutorPrompt.sourceMessageText,
        sourceMessageRole: selectionTutorPrompt.sourceMessageRole,
      },
      state.language,
    );
    setSelectionTutorPrompt(null);
    window.getSelection()?.removeAllRanges();
  }, [selectionTutorPrompt, state.language, state.sessionId]);

  const handleMessagesCopy = useCallback(
    (event: React.ClipboardEvent<HTMLDivElement>) => {
      const selection = window.getSelection();
      const container = messagesContainerRef.current;
      if (!selection || !container || selection.isCollapsed) return;
      if (
        !selection.rangeCount ||
        !container.contains(selection.getRangeAt(0).commonAncestorContainer)
      ) {
        return;
      }
      const remapped = textFromDomSelection(selection);
      const raw = normalizeSelectedText(selection.toString());
      if (!remapped || remapped === raw) return;
      event.clipboardData.setData("text/plain", remapped);
      event.preventDefault();
    },
    [messagesContainerRef],
  );

  const handleClosePreview = useCallback(() => {
    setPreviewSource(null);
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.types.includes("Files")) setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      dragCounter.current = 0;
      const accepted = filterAndReportFiles(Array.from(e.dataTransfer.files));
      if (!accepted.length) return;
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  const handleAddFiles = useCallback(
    async (files: File[]) => {
      const accepted = filterAndReportFiles(files);
      if (!accepted.length) return;
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  // Connected subagents are stored as ``type: subagent`` KBs. Derive the
  // selected one before the send callback so the callback can depend on the
  // current selection instead of capturing an undeclared-later value.
  const agentNameSet = useMemo(
    () =>
      new Set(
        knowledgeBases
          .filter((kb) => kb.metadata?.type === "subagent")
          .map((kb) => kb.name),
      ),
    [knowledgeBases],
  );
  const selectedAgent = useMemo(
    () => state.knowledgeBases.find((name) => agentNameSet.has(name)) ?? null,
    [state.knowledgeBases, agentNameSet],
  );
  // How many times DeepTutor may consult the selected agent this turn. Seeded
  // from the configured default; the composer's stepper overrides it per turn.
  const [subagentBudget, setSubagentBudget] = useState<number | null>(null);
  useEffect(() => {
    void getSubagentSettings()
      .then((settings) => setSubagentBudget(settings.consult_budget))
      .catch(() => undefined);
  }, []);

  const handleSend = useCallback(
    async (content: string) => {
      // A turn paused on a question: what the user typed is their answer, not
      // a new message. Routing it here means the card is one way to answer,
      // not the only one — and a card that never rendered no longer strands
      // the learner with a turn they can only cancel.
      if (awaitingUserReplyRef.current) {
        if (content.trim()) submitUserReply({ text: content });
        return;
      }
      if (
        (!content &&
          !attachments.length &&
          !selectedBookReferences.length &&
          !selectedReadingReferences.length &&
          !selectedNotebookRecords.length &&
          !selectedHistorySessions.length &&
          !selectedQuestionEntries.length &&
          !selectedMemoryFiles.length) ||
        state.isStreaming
      )
        return;

      const quizPrompt = content.trim().toLowerCase();
      const isPlaceholderQuizPrompt = new Set([
        "开始",
        "开始生成",
        "生成",
        "生成题目",
        "start",
        "generate",
      ]).has(quizPrompt);
      const hasQuizSource = Boolean(content.trim()) && !isPlaceholderQuizPrompt;
      if (
        isQuizMode &&
        quizConfig.mode === "custom" &&
        !hasQuizSource &&
        !attachments.length &&
        !selectedBookReferences.length &&
        !selectedNotebookRecords.length &&
        !selectedHistorySessions.length &&
        !selectedQuestionEntries.length &&
        !selectedMemoryFiles.length
      ) {
        setQuizValidationErrors([
          t(
            "Please provide a topic, for example: generate questions about limits.",
          ),
        ]);
        ensureActivityPanelOpen();
        return;
      }

      let extraAttachments = attachments.map((a) => ({
        type: a.type,
        filename: a.filename,
        base64: a.base64,
        mime_type: a.mimeType,
      }));
      let config: Record<string, unknown> | undefined;

      if (isQuizMode) {
        config = buildQuizWSConfig(quizConfig);
        if (quizConfig.mode === "mimic" && quizPdf) {
          const b64 = extractBase64FromDataUrl(
            await readFileAsDataUrl(quizPdf),
          );
          extraAttachments = [
            ...extraAttachments,
            {
              type: "pdf",
              filename: quizPdf.name,
              base64: b64,
              mime_type: "application/pdf",
            },
          ];
        }
      }
      if (isVisualizeMode) config = buildVisualizeWSConfig(visualizeConfig);
      if (isResearchMode) {
        if (!researchValidation.valid) return;
        config = buildResearchWSConfig(researchConfig);
      }
      // When a connected agent is selected, carry the per-turn consult budget
      // (how many times DeepTutor may ask it) so the subagent capability uses it.
      if (selectedAgent && subagentBudget) {
        config = { ...(config ?? {}), subagent_consult_budget: subagentBudget };
      }
      // Sent on every turn, including empty to mean "not in a course". The
      // server treats the key's presence as explicit and writes it to the
      // session's preferences, so the pill's state and the conversation's real
      // binding can never drift apart — and detaching actually detaches.
      config = { ...(config ?? {}), _course_id: courseId };

      const memoryPayload = [...memoryReferencesPayload];
      const messageContent =
        content ||
        (selectedNotebookRecords.length ||
        selectedBookReferences.length ||
        selectedReadingReferences.length ||
        selectedHistorySessions.length ||
        selectedAgentSessions.length ||
        selectedQuestionEntries.length ||
        memoryPayload.length
          ? t("Please use the selected context to help with this request.")
          : "") ||
        (attachments.some((a) => a.type === "image")
          ? t("Please analyze the attached image(s).")
          : "");
      // Persona is NOT passed per-call here: it is a session-level
      // preference (state.personaSelection) that sendMessage resolves and
      // sends with every turn.
      sendMessage(
        messageContent,
        extraAttachments,
        config,
        notebookReferencesPayload,
        historyReferencesPayload,
        {
          bookReferences: bookReferencesPayload,
          readingReferences: readingReferencesPayload,
        },
        questionNotebookReferencesPayload,
        undefined,
        memoryPayload,
      );
      shouldAutoScrollRef.current = true;
      setAttachments([]);
      setSelectedBookReferences([]);
      setSelectedReadingReferences([]);
      setSelectedNotebookRecords([]);
      setSelectedHistorySessions([]);
      setSelectedAgentSessions([]);
      setSelectedQuestionEntries([]);
      setSelectedMemoryFiles([]);
    },
    [
      attachments,
      bookReferencesPayload,
      courseId,
      readingReferencesPayload,
      historyReferencesPayload,
      isQuizMode,
      isResearchMode,
      isVisualizeMode,
      memoryReferencesPayload,
      notebookReferencesPayload,
      questionNotebookReferencesPayload,
      quizConfig,
      quizPdf,
      researchConfig,
      researchValidation,
      ensureActivityPanelOpen,
      selectedAgent,
      selectedHistorySessions.length,
      selectedAgentSessions.length,
      selectedMemoryFiles.length,
      selectedBookReferences.length,
      selectedReadingReferences.length,
      selectedNotebookRecords.length,
      selectedQuestionEntries.length,
      sendMessage,
      shouldAutoScrollRef,
      state.isStreaming,
      subagentBudget,
      submitUserReply,
      t,
      visualizeConfig,
    ],
  );

  const handleConfirmOutline = useCallback(
    (
      outline: OutlineItem[],
      _topic: string,
      originalConfig?: Record<string, unknown> | null,
      originalSnapshot?: MessageRequestSnapshot | null,
    ) => {
      const config: Record<string, unknown> = {
        ...(originalConfig ?? {
          mode: researchConfig.mode,
          depth: researchConfig.depth,
        }),
        confirmed_outline: outline,
      };
      const requestSnapshotOverride: MessageRequestSnapshot | undefined =
        originalSnapshot
          ? {
              ...originalSnapshot,
              content: _topic,
              capability: "deep_research",
              config,
            }
          : undefined;
      sendMessage(
        _topic,
        originalSnapshot?.attachments ?? [],
        config,
        originalSnapshot?.notebookReferences,
        originalSnapshot?.historyReferences,
        {
          displayUserMessage: false,
          persistUserMessage: false,
          requestSnapshotOverride,
          bookReferences: originalSnapshot?.bookReferences,
          readingReferences: originalSnapshot?.readingReferences,
        },
        originalSnapshot?.questionNotebookReferences,
        originalSnapshot?.persona,
        originalSnapshot?.memoryReferences,
      );
      shouldAutoScrollRef.current = true;
    },
    [researchConfig, sendMessage, shouldAutoScrollRef],
  );

  const handleRegenerateMessage = useCallback(() => {
    regenerateLastMessage();
  }, [regenerateLastMessage]);

  const handleToggleKB = useCallback(
    (name: string) => {
      const current = state.knowledgeBases;
      const providerOf = (kbName: string) => {
        const kb = knowledgeBases.find((item) => item.name === kbName);
        return kb?.metadata?.rag_provider || kb?.statistics?.rag_provider || "";
      };
      const selectingOss = providerOf(name) === "pageindex-oss";
      setKBs(
        current.includes(name)
          ? current.filter((kb) => kb !== name)
          : [
              ...(selectingOss
                ? current.filter((kb) => providerOf(kb) !== "pageindex-oss")
                : current),
              name,
            ],
      );
    },
    [knowledgeBases, setKBs, state.knowledgeBases],
  );

  // Real knowledge bases and connected subagents render as separate composer
  // controls even though both travel through the knowledge_bases request path.
  const kbOptions = useMemo(
    () => knowledgeBases.filter((kb) => kb.metadata?.type !== "subagent"),
    [knowledgeBases],
  );
  const agentOptions = useMemo(
    () =>
      knowledgeBases
        .filter((kb) => kb.metadata?.type === "subagent")
        .map((kb) => ({ name: kb.name, kind: kb.metadata?.agent_kind })),
    [knowledgeBases],
  );
  const selectedKbOnly = useMemo(
    () => state.knowledgeBases.filter((n) => !agentNameSet.has(n)),
    [state.knowledgeBases, agentNameSet],
  );
  const handleSelectAgent = useCallback(
    (name: string | null) => {
      // Single-select: clear any selected agent, then set the new one (if any).
      const withoutAgents = state.knowledgeBases.filter(
        (n) => !agentNameSet.has(n),
      );
      setKBs(name ? [...withoutAgents, name] : withoutAgents);
    },
    [setKBs, state.knowledgeBases, agentNameSet],
  );
  // Honor `?agent=<name>` once its connection KB has loaded: preselect it so a
  // partner opened from the partner list starts the chat already targeting it.
  useEffect(() => {
    if (agentPreselectDoneRef.current) return;
    const name = pendingAgentRef.current;
    if (!name || !agentNameSet.has(name)) return;
    agentPreselectDoneRef.current = true;
    handleSelectAgent(name);
  }, [agentNameSet, handleSelectAgent]);
  const handleSelectNotebookPicker = useCallback(() => {
    setShowNotebookPicker(true);
  }, []);
  const handleSelectBookPicker = useCallback(() => {
    setShowBookPicker(true);
  }, []);
  const handleSelectReadingPicker = useCallback(() => {
    setShowReadingPicker(true);
  }, []);
  const handleSelectHistoryPicker = useCallback(() => {
    setShowHistoryPicker(true);
  }, []);
  const handleSelectAgentsPicker = useCallback(() => {
    setShowAgentsPicker(true);
  }, []);
  const handleSelectQuestionBankPicker = useCallback(() => {
    setShowQuestionBankPicker(true);
  }, []);
  const handleSelectPersonaPicker = useCallback(() => {
    // The @space "Persona" entry now opens the session persona selector.
    setPersonaSelectorOpen(true);
  }, []);
  const handleSelectMemoryPicker = useCallback(() => {
    setShowMemoryPicker(true);
  }, []);
  const handleRemoveHistory = useCallback((sessionId: string) => {
    setSelectedHistorySessions((prev) =>
      prev.filter((item) => item.sessionId !== sessionId),
    );
  }, []);
  const handleRemoveAgent = useCallback((sessionId: string) => {
    setSelectedAgentSessions((prev) =>
      prev.filter((item) => item.sessionId !== sessionId),
    );
  }, []);
  const handleRemoveNotebook = useCallback((notebookId: string) => {
    setSelectedNotebookRecords((prev) =>
      prev.filter((record) => record.notebookId !== notebookId),
    );
  }, []);
  const handleRemoveBookReference = useCallback((bookId: string) => {
    setSelectedBookReferences((prev) =>
      prev.filter((record) => record.bookId !== bookId),
    );
  }, []);
  const handleRemoveReadingReference = useCallback((materialId: string) => {
    setSelectedReadingReferences((previous) =>
      previous.filter((record) => record.materialId !== materialId),
    );
  }, []);
  const handleRemoveQuestion = useCallback((entryId: number) => {
    setSelectedQuestionEntries((prev) =>
      prev.filter((entry) => entry.id !== entryId),
    );
  }, []);
  const handleClearPersona = useCallback(() => {
    setPersonaSelection("");
  }, [setPersonaSelection]);

  const handleToggleMemoryFile = useCallback((file: SpaceMemoryFile) => {
    setSelectedMemoryFiles((prev) =>
      prev.includes(file)
        ? prev.filter((item) => item !== file)
        : [...prev, file],
    );
  }, []);

  const handleCloseNotebookPicker = useCallback(() => {
    setShowNotebookPicker(false);
  }, []);
  const handleCloseBookPicker = useCallback(() => {
    setShowBookPicker(false);
  }, []);
  const handleCloseReadingPicker = useCallback(() => {
    setShowReadingPicker(false);
  }, []);
  const handleApplyBookReferences = useCallback(
    (references: SelectedBookReference[]) => {
      setSelectedBookReferences(references);
    },
    [],
  );
  const handleApplyReadingReferences = useCallback(
    (references: SelectedReadingReference[]) => {
      setSelectedReadingReferences(references);
    },
    [],
  );
  const handleApplyNotebookRecords = useCallback(
    (records: SelectedRecord[]) => {
      setSelectedNotebookRecords(records);
    },
    [],
  );
  const handleCloseHistoryPicker = useCallback(() => {
    setShowHistoryPicker(false);
  }, []);
  const handleApplyHistorySessions = useCallback(
    (sessions: SelectedHistorySession[]) => {
      setSelectedHistorySessions(sessions);
    },
    [],
  );
  const handleCloseAgentsPicker = useCallback(() => {
    setShowAgentsPicker(false);
  }, []);
  const handleApplyAgentSessions = useCallback(
    (sessions: SelectedHistorySession[]) => {
      setSelectedAgentSessions(sessions);
    },
    [],
  );
  const handleCloseQuestionBankPicker = useCallback(() => {
    setShowQuestionBankPicker(false);
  }, []);
  const handleApplyQuestionEntries = useCallback(
    (entries: SelectedQuestionEntry[]) => {
      setSelectedQuestionEntries(entries);
    },
    [],
  );
  const handleCloseMemoryPicker = useCallback(() => {
    setShowMemoryPicker(false);
  }, []);
  const handleApplyMemoryFiles = useCallback((files: SpaceMemoryFile[]) => {
    setSelectedMemoryFiles(files);
  }, []);
  const handleCloseSaveModal = useCallback(() => {
    setShowSaveModal(false);
  }, []);

  const handleDownloadMarkdown = useCallback(() => {
    if (!state.messages.length) return;
    const title =
      state.messages
        .find((msg) => msg.role === "user")
        ?.content.trim()
        .slice(0, 80) || "Chat Session";
    downloadChatMarkdown(state.messages, { title });
  }, [state.messages]);

  return (
    <QuizFollowupProvider>
      <GeogebraTabProvider>
        <QuizFollowupBridge viewerPanelRef={viewerPanelRef} />
        <GeogebraTabBridge viewerPanelRef={viewerPanelRef} />
        <SubagentTabWatcher
          messages={state.messages}
          viewerPanelRef={viewerPanelRef}
        />
        <div className="relative h-full overflow-hidden">
          {/* The video panel slides in from the left and the chat column shrinks to
            make room. Rendered as a sibling with its own transform rather than
            wrapping the chat, so switching modes never remounts the chat tree —
            a remount would refetch every piece of session metadata and stall the
            UI for seconds (the regression behind the slow session-open bug). */}
          <div
            data-watching-open={isWatchingMode ? "true" : "false"}
            className="dt-watching-shell"
          >
            {isWatchingMode && (
              <WatchingPane onClose={() => setCapability("")} />
            )}
          </div>
          <div
            // When the preview drawer is open AND the viewport is wide enough,
            // push the chat content to the left by the drawer's width so the two
            // panels live side-by-side (matches Claude desktop). On smaller
            // screens the drawer overlays — squeezing a phone-width chat into
            // the remaining ~30 px would be useless. The actual padding +
            // transition lives in `chat-preview-shell` (globals.css) so we can
            // hand-tune it without fighting Tailwind's arbitrary-value parser.
            data-preview-open={previewSource ? "true" : "false"}
            data-viewer-open={viewerPanelOpen ? "true" : "false"}
            data-watching-open={isWatchingMode ? "true" : "false"}
            className="chat-preview-shell flex h-full flex-col overflow-hidden bg-[var(--background)]"
          >
            <div className="mx-auto flex w-full max-w-[960px] flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-6 pt-3 pb-0">
              <div className="group/title min-w-0 flex flex-1 items-center gap-2">
                {sessionTitleEditing ? (
                  <input
                    ref={titleInputRef}
                    value={sessionTitleDraft}
                    onChange={(event) =>
                      setSessionTitleDraft(event.target.value)
                    }
                    onBlur={() => void commitSessionTitleEdit()}
                    onKeyDown={handleSessionTitleKeyDown}
                    disabled={sessionTitleSaving}
                    aria-label={t("Session title")}
                    className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 font-serif text-[17px] font-semibold tracking-[-0.01em] text-[var(--foreground)] shadow-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/20 disabled:opacity-60"
                    maxLength={100}
                  />
                ) : (
                  <button
                    type="button"
                    onClick={startSessionTitleEdit}
                    disabled={!canRenameSession}
                    title={
                      canRenameSession
                        ? t("Click to rename session")
                        : t("Start a conversation to rename")
                    }
                    className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-xl px-2 py-1 text-left font-serif text-[17px] font-semibold tracking-[-0.01em] text-[var(--foreground)] transition hover:bg-[var(--muted)]/55 disabled:cursor-default disabled:hover:bg-transparent"
                  >
                    <span className="truncate">{displaySessionTitle}</span>
                    {canRenameSession ? (
                      <PenLine className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover/title:opacity-100" />
                    ) : null}
                  </button>
                )}
                {sessionTitleSaving ? (
                  <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                    {t("Saving...")}
                  </span>
                ) : null}
                {sessionTitleError ? (
                  <span className="shrink-0 text-xs text-[var(--destructive)]">
                    {sessionTitleError}
                  </span>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                <HeaderActionButton
                  onClick={() => setShowSaveModal(true)}
                  disabled={!chatSavePayload}
                  icon={BookmarkPlus}
                  label={t("Save to Notebook")}
                />
                <HeaderActionButton
                  onClick={handleDownloadMarkdown}
                  disabled={!state.messages.length}
                  icon={Download}
                  label={t("Download Markdown")}
                  title={t("Download chat history as Markdown")}
                />
                <HeaderActionButton
                  onClick={() => viewerPanelRef.current?.openMarkdownNoteTab()}
                  icon={NotebookPen}
                  label={t("Markdown note")}
                  title={t("Write Markdown in chat")}
                />
                <HeaderActionButton
                  onClick={toggleViewerPanel}
                  active={viewerPanelOpen}
                  icon={PanelRight}
                  label={t("Activity")}
                  title={t("Session activity, attachments & previews")}
                />
              </div>
            </div>
            <div className="flex w-full flex-1 min-h-0 flex-col">
              {sessionLoading || sessionLoadFailed ? (
                <div className="flex w-full flex-1 min-h-0 justify-center px-6">
                  <div className="h-full w-full max-w-[960px]">
                    <SessionLoadingView
                      onCancel={cancelSessionLoad}
                      failed={sessionLoadFailed}
                      onRetry={retrySessionLoad}
                    />
                  </div>
                </div>
              ) : !hasMessages ? (
                <div className="flex w-full flex-1 min-h-0 items-end justify-center pb-14 animate-fade-in px-6">
                  <div className="w-full max-w-[960px] flex items-center justify-center gap-4">
                    <img
                      src="/logo_black.png"
                      alt="DeepTutor"
                      width={40}
                      height={40}
                      className="h-10 w-10 select-none"
                      draggable={false}
                    />
                    <h1 className="font-serif text-[40px] font-medium leading-[1.1] tracking-[-0.015em] text-[var(--foreground)]">
                      {t(welcomeGreeting)}
                    </h1>
                  </div>
                </div>
              ) : (
                // Positioned wrapper spanning exactly the scrollport, so the
                // turn navigator can overlay the left gutter without living
                // inside the masked scroll container (its top/bottom fade
                // would clip the rail's ends).
                <div className="relative flex w-full flex-1 min-h-0 flex-col">
                  <div
                    ref={messagesContainerRef}
                    data-chat-scroll-root="true"
                    onScroll={() => {
                      setSelectionTutorPrompt(null);
                      handleMessagesScroll();
                    }}
                    onClick={handleMessagesClick}
                    onCopy={handleMessagesCopy}
                    onMouseUp={handleMessagesSelection}
                    onKeyUp={handleMessagesSelection}
                    // `both-edges` reserves the scrollbar gutter on both sides so
                    // the inner mx-auto column centers on the same axis as the
                    // header and composer (siblings outside this scrollport) on
                    // classic-scrollbar platforms; plain `stable` would shift it
                    // ~half a scrollbar-width left of them.
                    className={`w-full flex-1 min-h-0 overflow-y-auto [scrollbar-gutter:stable_both-edges] ${hasMessages ? "pt-6" : "pt-2 pb-6"}`}
                    style={
                      hasMessages
                        ? (() => {
                            // The bottom 40 px of the messages area fades to
                            // transparent so content "dissolves" into the composer
                            // gutter. Without enough bottom padding, the fade
                            // overlaps the last assistant paragraph and looks like
                            // a stuck scroll — the user reaches scrollHeight but
                            // can still see only a faded sliver of text. paddingBottom
                            // is sized so the fade falls over empty space.
                            const maskImage =
                              "linear-gradient(to bottom, transparent 0px, #000 32px, #000 calc(100% - 40px), transparent 100%)";
                            return {
                              paddingBottom: "48px",
                              WebkitMaskImage: maskImage,
                              maskImage,
                            };
                          })()
                        : undefined
                    }
                  >
                    <div
                      data-chat-column="true"
                      className="mx-auto w-full max-w-[960px] space-y-9 px-6"
                    >
                      <ChatMessageList
                        messages={state.messages}
                        isStreaming={state.isStreaming}
                        sessionId={state.sessionId}
                        language={state.language}
                        onCopyAssistantMessage={copyAssistantMessage}
                        onRegenerateMessage={handleRegenerateMessage}
                        onConfirmOutline={handleConfirmOutline}
                        onPreviewAttachment={handlePreviewMessageAttachment}
                        onDeleteTurn={deleteTurn}
                        selectedBranches={state.selectedBranches}
                        onEditMessage={editMessage}
                        onSwitchBranch={switchBranch}
                        onSubmitUserReply={submitUserReply}
                        onLoadMessageTrace={(messageId) =>
                          state.sessionId
                            ? loadMessageTrace(state.sessionId, messageId)
                            : Promise.resolve()
                        }
                        onReleaseMessageTrace={(messageId) => {
                          if (state.sessionId) {
                            releaseMessageTrace(state.sessionId, messageId);
                          }
                        }}
                        availableKbNames={
                          knowledgeBasesLoaded ? availableKbNames : undefined
                        }
                      />
                      <div
                        ref={messagesEndRef}
                        className="h-px w-full shrink-0"
                      />
                    </div>
                  </div>
                  {selectionTutorPrompt ? (
                    <button
                      type="button"
                      onPointerDown={(event) => event.preventDefault()}
                      onClick={openSelectionTutor}
                      aria-label={t("Ask Little Tutor")}
                      className="fixed z-[45] inline-flex h-[38px] items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--foreground)] px-3 text-[12px] font-medium text-[var(--background)] shadow-lg transition-transform hover:-translate-y-0.5"
                      style={{
                        left: selectionTutorPrompt.left,
                        top: selectionTutorPrompt.top,
                      }}
                    >
                      <GraduationCap size={15} strokeWidth={1.8} />
                      {t("Ask Little Tutor")}
                    </button>
                  ) : null}
                  <TurnNavigator
                    entries={chatOutline}
                    scrollRootRef={messagesContainerRef}
                    onJump={jumpToTurn}
                    onJumpToBottom={resumeFollowingLatest}
                  />
                </div>
              )}

              <ChatComposer
                composerRef={composerRef}
                capMenuRef={capMenuRef}
                capBtnRef={capBtnRef}
                spaceMenuRef={spaceMenuRef}
                spaceBtnRef={spaceBtnRef}
                dragCounter={dragCounter}
                dragging={dragging}
                capMenuOpen={capMenuOpen}
                courses={courses}
                courseId={courseId}
                // onSelectCourse intentionally omitted: hides the CoursePill
                // entry point while courseId keeps flowing to the backend for
                // conversations already bound (e.g. via a course deep link).
                spaceMenuOpen={spaceMenuOpen}
                hasMessages={hasMessages}
                attachments={attachments}
                attachmentError={attachmentError}
                activeCap={activeCap}
                knowledgeBases={kbOptions}
                connectedAgents={agentOptions}
                selectedAgent={selectedAgent}
                onSelectAgent={handleSelectAgent}
                subagentBudget={subagentBudget}
                onSubagentBudgetChange={setSubagentBudget}
                llmOptions={llmOptions}
                activeLLMDefault={activeLLMDefault}
                llmSelection={state.llmSelection}
                llmOptionsLoading={llmOptionsLoading}
                llmOptionsError={llmOptionsError}
                onRefreshLLMOptions={() =>
                  void refreshLLMOptions({ force: true })
                }
                contextBudget={contextBudget}
                selectedBookReferences={selectedBookReferences}
                selectedReadingReferences={selectedReadingReferences}
                selectedNotebookRecords={selectedNotebookRecords}
                selectedHistorySessions={selectedHistorySessions}
                selectedAgentSessions={selectedAgentSessions}
                selectedQuestionEntries={selectedQuestionEntries}
                notebookReferenceGroups={notebookReferenceGroups}
                selectedPersona={null}
                selectedMemoryFiles={selectedMemoryFiles}
                selectedKnowledgeBases={selectedKbOnly}
                isStreaming={state.isStreaming}
                isVisualizeMode={isVisualizeMode}
                capabilityNeedsConfig={capabilityNeedsConfig}
                capabilityConfigConfirmed={capabilityConfigConfirmed}
                onRequestConfigConfirm={ensureActivityPanelOpen}
                capabilities={visibleCapabilities}
                onSetCapMenuOpen={setCapMenuOpen}
                onSetSpaceMenuOpen={setSpaceMenuOpen}
                onToggleKB={handleToggleKB}
                onSelectLLM={setLLMSelection}
                onSelectNotebookPicker={handleSelectNotebookPicker}
                onSelectBookPicker={handleSelectBookPicker}
                onSelectReadingPicker={handleSelectReadingPicker}
                onSelectHistoryPicker={handleSelectHistoryPicker}
                onSelectAgentsPicker={handleSelectAgentsPicker}
                onSelectQuestionBankPicker={handleSelectQuestionBankPicker}
                onSelectPersonaPicker={handleSelectPersonaPicker}
                onSelectMemoryPicker={handleSelectMemoryPicker}
                onClearPersona={handleClearPersona}
                personaSelection={state.personaSelection}
                onPersonaSelectionChange={setPersonaSelection}
                personaSelectorOpen={personaSelectorOpen}
                onPersonaSelectorOpenChange={setPersonaSelectorOpen}
                onToggleMemoryFile={handleToggleMemoryFile}
                onSend={handleSend}
                awaitingUserReply={awaitingUserReply}
                onRemoveAttachment={removeAttachment}
                onPreviewAttachment={handlePreviewPendingAttachment}
                onRemoveHistory={handleRemoveHistory}
                onRemoveAgent={handleRemoveAgent}
                onRemoveBookReference={handleRemoveBookReference}
                onRemoveReadingReference={handleRemoveReadingReference}
                onRemoveNotebook={handleRemoveNotebook}
                onRemoveQuestion={handleRemoveQuestion}
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onPaste={handlePaste}
                onAddFiles={handleAddFiles}
                onSelectCapability={handleSelectCapability}
                onCancelStreaming={cancelStreamingTurn}
                prefillInputRef={prefillInputRef}
                inputPlaceholder={askHint || undefined}
                inputPlaceholderCompletion={askHint}
              />
              {/* Starter chips sit between the composer and the spacer, so they
                ride up with the composer on the empty screen and disappear the
                moment the conversation has a first message. Clicking one sends
                it through the normal send path: this page is already a draft
                session when it has no messages, so that both creates the
                session and starts it on the topic. */}
              {!hasMessages ? (
                <StarterSuggestions
                  onPick={(prompt) => void handleSend(prompt)}
                  disabled={state.isStreaming}
                />
              ) : null}
              <div
                aria-hidden="true"
                className="shrink-0"
                style={{
                  flexGrow: hasMessages ? 0 : 1.4,
                  transition: "flex-grow 650ms cubic-bezier(0.16, 1, 0.3, 1)",
                }}
              />
            </div>
            <NotebookRecordPicker
              open={showNotebookPicker}
              onClose={handleCloseNotebookPicker}
              onApply={handleApplyNotebookRecords}
            />
            <BookReferencePicker
              open={showBookPicker}
              initialReferences={selectedBookReferences}
              onClose={handleCloseBookPicker}
              onApply={handleApplyBookReferences}
            />
            <ReadingReferencePicker
              open={showReadingPicker}
              initialReferences={selectedReadingReferences}
              onClose={handleCloseReadingPicker}
              onApply={handleApplyReadingReferences}
            />
            <HistorySessionPicker
              open={showHistoryPicker}
              onClose={handleCloseHistoryPicker}
              onApply={handleApplyHistorySessions}
            />
            <MyAgentsPicker
              open={showAgentsPicker}
              onClose={handleCloseAgentsPicker}
              onApply={handleApplyAgentSessions}
            />
            <QuestionBankPicker
              open={showQuestionBankPicker}
              onClose={handleCloseQuestionBankPicker}
              onApply={handleApplyQuestionEntries}
            />
            <MemoryPicker
              open={showMemoryPicker}
              initialFiles={selectedMemoryFiles}
              onClose={handleCloseMemoryPicker}
              onApply={handleApplyMemoryFiles}
            />
            <SaveToNotebookModal
              open={showSaveModal}
              payload={chatSavePayload}
              messages={chatSaveMessages}
              onClose={handleCloseSaveModal}
            />
            <FilePreviewDrawer
              open={previewSource !== null}
              source={previewSource}
              onClose={handleClosePreview}
            />
            <SessionViewerPanel
              ref={viewerPanelRef}
              open={viewerPanelOpen && previewSource === null}
              sessionId={state.sessionId}
              activity={sessionActivity}
              configSection={capabilityConfigSection}
              onClose={() => setViewerOpen(false)}
              onAutoOpen={() => setViewerOpen(true)}
            />
          </div>
        </div>
      </GeogebraTabProvider>
    </QuizFollowupProvider>
  );
}

/**
 * Bridges the SessionViewerPanel's imperative ``openQuizFollowupTab`` into
 * the QuizFollowupController so descendants (QuizViewer) can call
 * ``controller.openFollowupTab(...)`` without prop-drilling the panel ref
 * through several layers of components.
 */
function QuizFollowupBridge({
  viewerPanelRef,
}: {
  viewerPanelRef: React.MutableRefObject<SessionViewerPanelHandle | null>;
}) {
  const controller = useQuizFollowupController();
  useEffect(() => {
    controller.setOpenTabHandler((ctx) => {
      viewerPanelRef.current?.openQuizFollowupTab(ctx);
    });
    return () => controller.setOpenTabHandler(null);
  }, [controller, viewerPanelRef]);
  return null;
}

/**
 * Same shape as QuizFollowupBridge, for the GeoGebra-tab opener exposed
 * to in-message CTAs (the ``ggbscript`` markdown fence becomes a card
 * that calls ``controller.openTab(...)`` here).
 */
function GeogebraTabBridge({
  viewerPanelRef,
}: {
  viewerPanelRef: React.MutableRefObject<SessionViewerPanelHandle | null>;
}) {
  const controller = useGeogebraTabOpener();
  useEffect(() => {
    if (!controller) return;
    controller.setOpenHandler((payload) => {
      viewerPanelRef.current?.openGeogebraTab(payload);
    });
    return () => controller.setOpenHandler(null);
  }, [controller, viewerPanelRef]);
  return null;
}

/**
 * Watches the turn's messages for connected-subagent runs and mirrors each
 * (grouped by the consult's call id) into its own side-viewer tab — opening +
 * focusing the panel when a consult starts, then live-refreshing as the
 * agent's native events stream in. Keeps the chat trace compact while the full
 * run shows in the sidebar.
 */
function SubagentTabWatcher({
  messages,
  viewerPanelRef,
}: {
  messages: { events?: StreamEvent[] }[];
  viewerPanelRef: React.MutableRefObject<SessionViewerPanelHandle | null>;
}) {
  useEffect(() => {
    // Group by turn so all of one turn's consults (DeepTutor may ask the agent
    // several questions in a row, each its own tool call) land in one tab as a
    // single running dialogue; fall back to the call id when no turn is set.
    const groups = new Map<string, { label: string; events: StreamEvent[] }>();
    for (const msg of messages) {
      for (const ev of msg.events ?? []) {
        const meta = (ev.metadata ?? {}) as Record<string, unknown>;
        if (meta.trace_kind !== "subagent_event") continue;
        const key = String(meta.turn_id || meta.call_id || meta.trace_id || "");
        if (!key) continue;
        const existing = groups.get(key);
        const label = String(
          meta.subagent_name || existing?.label || "Subagent",
        );
        if (existing) {
          existing.label = label;
          existing.events.push(ev);
        } else {
          groups.set(key, { label, events: [ev] });
        }
      }
    }
    for (const [key, group] of groups) {
      viewerPanelRef.current?.openSubagentTab(key, group.label, group.events);
    }
  }, [messages, viewerPanelRef]);
  return null;
}

/**
 * Header action button that auto-collapses to icon-only when the chat
 * column gets squeezed (Viewer panel open, narrow viewport, etc.). The
 * label stays as the button's `title` so hovering an icon still reveals
 * what it does. Optional `active` flag paints the button with a primary
 * tint, used by the panel-toggle buttons to surface their on/off state.
 */
// Claude-style icon-only header action: bare 16px glyph, function revealed
// by an instant tooltip; active state gets a primary tint.
function HeaderActionButton({
  onClick,
  disabled,
  active,
  icon: Icon,
  label,
  title,
}: {
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  icon: LucideIcon;
  label: string;
  title?: string;
}) {
  return (
    <Tooltip label={title ?? label} side="bottom">
      <button
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={active}
        className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40 ${
          active
            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)] disabled:hover:bg-transparent disabled:hover:text-[var(--muted-foreground)]"
        }`}
      >
        <Icon size={16} strokeWidth={1.7} className="shrink-0" />
      </button>
    </Tooltip>
  );
}
