"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  BarChart3,
  BrainCircuit,
  Clapperboard,
  Code2,
  Database,
  FileSearch,
  Globe,
  Lightbulb,
  MessageSquare,
  Microscope,
  PenLine,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedRecord } from "@/lib/notebook-selection-types";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import ChatComposer from "@/components/chat/home/ChatComposer";
import { ChatMessageList } from "@/components/chat/home/ChatMessages";
// Imported eagerly so the drawer shell is always mounted off-screen —
// clicking a chip becomes a single CSS class flip, no chunk fetch + double
// render. The heavy renderers inside still load lazily.
import FilePreviewDrawer from "@/components/chat/preview/FilePreviewDrawer";
import SessionActivityPanel, {
  buildSessionActivity,
} from "@/components/chat/home/SessionActivityPanel";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import {
  BookmarkPlus,
  BookOpen,
  Download,
  PanelRight,
  SquarePen,
} from "lucide-react";
import {
  useUnifiedChat,
  type MessageAttachment,
  type MessageRequestSnapshot,
} from "@/context/UnifiedChatContext";
import { useAppShell } from "@/context/AppShellContext";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import type { LLMSelection, StreamEvent } from "@/lib/unified-ws";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";
import {
  classifyFile,
  isSvgFilename,
  MAX_ATTACHMENT_BYTES,
  MAX_TOTAL_ATTACHMENT_BYTES,
} from "@/lib/doc-attachments";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import {
  loadCapabilityPlaygroundConfigs,
  resolveCapabilityPlaygroundConfig,
  type CapabilityPlaygroundConfigMap,
} from "@/lib/playground-config";
import {
  DEFAULT_QUIZ_CONFIG,
  buildQuizWSConfig,
  type DeepQuestionFormConfig,
} from "@/lib/quiz-types";
import {
  DEFAULT_MATH_ANIMATOR_CONFIG,
  buildMathAnimatorWSConfig,
  type MathAnimatorFormConfig,
} from "@/lib/math-animator-types";
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
  type ResearchSource,
} from "@/lib/research-types";
import {
  applyChatRetrievalMode,
  type ChatRetrievalMode,
} from "@/lib/chat-retrieval-mode";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import { listLLMOptions, type LLMOption } from "@/lib/llm-options";
import { downloadChatMarkdown } from "@/lib/chat-export";
import type { SpaceMemoryFile } from "@/lib/space-items";
import {
  selectedBooksToPayload,
  type SelectedBookReference,
} from "@/lib/book-references";

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
const QuestionBankPicker = dynamic(
  () => import("@/components/chat/QuestionBankPicker"),
  {
    ssr: false,
  },
);
const SkillsPicker = dynamic(() => import("@/components/chat/SkillsPicker"), {
  ssr: false,
});
const MemoryPicker = dynamic(() => import("@/components/chat/MemoryPicker"), {
  ssr: false,
});
const BookReferencePicker = dynamic(
  () => import("@/components/chat/BookReferencePicker"),
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
  { ssr: false },
);
const QuizConfigPanel = dynamic(
  () => import("@/components/quiz/QuizConfigPanel"),
  { ssr: false },
);
const MathAnimatorConfigPanel = dynamic(
  () => import("@/components/math-animator/MathAnimatorConfigPanel"),
  { ssr: false },
);
const VisualizeConfigPanel = dynamic(
  () => import("@/components/visualize/VisualizeConfigPanel"),
  { ssr: false },
);
const ResearchConfigPanel = dynamic(
  () => import("@/components/research/ResearchConfigPanel"),
  { ssr: false },
);

/* ------------------------------------------------------------------ */
/*  Type & data definitions                                           */
/* ------------------------------------------------------------------ */

type ToolName =
  | "brainstorm"
  | "web_search"
  | "code_execution"
  | "reason"
  | "paper_search";

interface ToolDef {
  name: ToolName;
  label: string;
  icon: LucideIcon;
}

interface ResearchSourceDef {
  name: ResearchSource;
  label: string;
  icon: LucideIcon;
}

const ALL_TOOLS: ToolDef[] = [
  { name: "brainstorm", label: "Brainstorm", icon: Lightbulb },
  { name: "web_search", label: "Web Search", icon: Globe },
  { name: "code_execution", label: "Code", icon: Code2 },
  { name: "reason", label: "Reason", icon: Sparkles },
  { name: "paper_search", label: "Arxiv Search", icon: FileSearch },
];

const RESEARCH_SOURCES: ResearchSourceDef[] = [
  { name: "kb", label: "Knowledge Base", icon: Database },
  { name: "web", label: "Web", icon: Globe },
  { name: "papers", label: "Papers", icon: FileSearch },
];

interface CapabilityDef {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  allowedTools: ToolName[];
  defaultTools: ToolName[];
}

const CAPABILITIES: CapabilityDef[] = [
  {
    value: "",
    label: "Chat",
    description: "Flexible conversation with any tool",
    icon: MessageSquare,
    allowedTools: [
      "brainstorm",
      "web_search",
      "code_execution",
      "reason",
      "paper_search",
    ],
    defaultTools: [],
  },
  {
    value: "deep_solve",
    label: "Solve",
    description: "Multi-step reasoning & problem solving",
    icon: BrainCircuit,
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: ["web_search", "code_execution", "reason"],
  },
  {
    value: "deep_question",
    label: "Quiz",
    description: "Auto-validated question generation",
    icon: PenLine,
    allowedTools: ["web_search", "code_execution"],
    defaultTools: ["web_search", "code_execution"],
  },
  {
    value: "deep_research",
    label: "Research",
    description: "Comprehensive multi-agent research",
    icon: Microscope,
    allowedTools: [],
    defaultTools: [],
  },
  {
    value: "math_animator",
    label: "Animator",
    description: "Generate math videos or storyboard images",
    icon: Clapperboard,
    allowedTools: [],
    defaultTools: [],
  },
  {
    value: "visualize",
    label: "Visualize",
    description: "Generate SVG, Chart.js, or Mermaid visualizations",
    icon: BarChart3,
    allowedTools: [],
    defaultTools: [],
  },
];

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
}

interface PendingAttachment {
  type: string;
  filename: string;
  base64?: string;
  previewUrl?: string;
  size?: number;
  mimeType?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

// ChatComposer still accepts isAutoMode/autoEnabledCaps/onToggleAutoCap so that
// the same component can also be reused by the /co-learn page. Manual chat
// always passes these dummies — the auto multi-select popover is never shown.
const EMPTY_SET = new Set<string>();
const noopToggleAutoCap = (_cap: string) => undefined;

function getCapability(value: string | null): CapabilityDef {
  return CAPABILITIES.find((c) => c.value === (value || "")) ?? CAPABILITIES[0];
}

/* ------------------------------------------------------------------ */
/*  Chat page                                                         */
/* ------------------------------------------------------------------ */

export default function ChatPage() {
  const params = useParams<{ sessionId?: string[] }>();
  const router = useRouter();
  const { t } = useTranslation();
  const sessionIdParam = params.sessionId?.[0] ?? null;
  const { setActiveSessionId, language: appLanguage } = useAppShell();

  const {
    state,
    setTools,
    setCapability,
    setKBs,
    setLLMSelection,
    sendMessage,
    cancelStreamingTurn,
    regenerateLastMessage,
    deleteTurn,
    editMessage,
    switchBranch,
    newSession,
    loadSession,
  } = useUnifiedChat();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [llmOptions, setLLMOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(
    null,
  );
  const [llmOptionsLoading, setLLMOptionsLoading] = useState(true);
  const [llmOptionsError, setLLMOptionsError] = useState(false);
  const [capabilityConfigs, setCapabilityConfigs] =
    useState<CapabilityPlaygroundConfigMap>({});
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [previewSource, setPreviewSource] = useState<FilePreviewSource | null>(
    null,
  );
  // When the chat column squeezes (e.g. the Viewer panel opens), the header
  // action labels can collide. We measure the actual header width and flip
  // to icon-only buttons below a threshold so the row never overflows.
  // Important: read full border-box width via getBoundingClientRect — the
  // ResizeObserverEntry.contentRect excludes the header's px-6 padding
  // (48 px), which makes a "naive" threshold land 48 px below where labels
  // actually start colliding.
  const headerRef = useRef<HTMLDivElement | null>(null);
  const [headerMeasuredWidth, setHeaderMeasuredWidth] = useState<number>(
    Number.POSITIVE_INFINITY,
  );
  useEffect(() => {
    const el = headerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    setHeaderMeasuredWidth(el.getBoundingClientRect().width);
    const observer = new ResizeObserver(() => {
      // entry.contentRect drops padding; the visual collision happens at
      // border-box width, so read it directly off the element.
      if (headerRef.current) {
        setHeaderMeasuredWidth(
          headerRef.current.getBoundingClientRect().width,
        );
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  // Right-side panels — Activity (floating cards) and Viewer (full sidebar
  // with tabs for file previews + web pages). Each independently togglable
  // and persisted across reloads.
  //
  // We initialise both to `false` so the SSR-rendered HTML matches the
  // first client render exactly (no hydration mismatch). The persisted
  // preference is then applied in a post-mount effect below.
  const [activityPanelOpen, setActivityPanelOpen] = useState(false);
  const [viewerPanelOpen, setViewerPanelOpen] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem("dt:chat:activity-panel") === "1") {
      setActivityPanelOpen(true);
    }
    if (window.localStorage.getItem("dt:chat:viewer-panel") === "1") {
      setViewerPanelOpen(true);
    }
  }, []);
  const toggleActivityPanel = useCallback(() => {
    setActivityPanelOpen((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(
          "dt:chat:activity-panel",
          next ? "1" : "0",
        );
      }
      return next;
    });
  }, []);
  /**
   * Force the Activity panel open. Used by the send-gate when the user
   * tries to send while the active capability still needs its config
   * confirmed — we surface the right-side panel so the Confirm button is
   * visible. Persisted to localStorage so subsequent reloads remember the
   * preference. Also used by the capability-switch auto-open effect below.
   */
  const ensureActivityPanelOpen = useCallback(() => {
    setActivityPanelOpen((prev) => {
      if (prev) return prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem("dt:chat:activity-panel", "1");
      }
      return true;
    });
  }, []);
  const setViewerOpen = useCallback((next: boolean) => {
    setViewerPanelOpen(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("dt:chat:viewer-panel", next ? "1" : "0");
    }
  }, []);
  const toggleViewerPanel = useCallback(() => {
    setViewerPanelOpen((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(
          "dt:chat:viewer-panel",
          next ? "1" : "0",
        );
      }
      return next;
    });
  }, []);
  // The header's five labelled actions ("Save to Notebook" / "Download
  // Markdown" / "New chat" / "Activity" / "Viewer") need roughly 720 px
  // (label widths + gaps + the capability title) to fit on one row without
  // colliding. Below that we collapse all five to icon-only. We also
  // force-collapse whenever the Viewer panel is open — its squeeze is
  // aggressive enough that labels are guaranteed to overflow.
  const headerCompact = viewerPanelOpen || headerMeasuredWidth < 720;
  const attachmentErrorTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const [quizConfig, setQuizConfig] = useState<DeepQuestionFormConfig>({
    ...DEFAULT_QUIZ_CONFIG,
  });
  const [quizPdf, setQuizPdf] = useState<File | null>(null);
  const [mathAnimatorConfig, setMathAnimatorConfig] =
    useState<MathAnimatorFormConfig>({
      ...DEFAULT_MATH_ANIMATOR_CONFIG,
    });
  const [visualizeConfig, setVisualizeConfig] = useState<VisualizeFormConfig>({
    ...DEFAULT_VISUALIZE_CONFIG,
  });
  const [researchConfig, setResearchConfig] = useState<DeepResearchFormConfig>(
    createEmptyResearchConfig(),
  );
  // Capability-config confirmation gate.
  //
  // For capabilities that need explicit configuration (Quiz, Animator,
  // Visualize, Research), the user must click *Confirm* in the right-side
  // Activity panel before sending. Any subsequent edit to the underlying
  // config invalidates the confirmation, so the user re-confirms once
  // they've adjusted settings. Capability switches also reset this flag.
  const [capabilityConfigConfirmed, setCapabilityConfigConfirmed] =
    useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [showBookPicker, setShowBookPicker] = useState(false);
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showQuestionBankPicker, setShowQuestionBankPicker] = useState(false);
  const [showSkillsPicker, setShowSkillsPicker] = useState(false);
  const [showMemoryPicker, setShowMemoryPicker] = useState(false);
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [spaceMenuOpen, setSpaceMenuOpen] = useState(false);
  const [kbMenuOpen, setKbMenuOpen] = useState(false);
  const [chatRetrievalMode, setChatRetrievalMode] =
    useState<ChatRetrievalMode>("auto");
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<
    SelectedRecord[]
  >([]);
  const [selectedBookReferences, setSelectedBookReferences] = useState<
    SelectedBookReference[]
  >([]);
  const [selectedHistorySessions, setSelectedHistorySessions] = useState<
    SelectedHistorySession[]
  >([]);
  const [selectedQuestionEntries, setSelectedQuestionEntries] = useState<
    SelectedQuestionEntry[]
  >([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [skillsAutoMode, setSkillsAutoMode] = useState(false);
  const [selectedMemoryFiles, setSelectedMemoryFiles] = useState<
    SpaceMemoryFile[]
  >([]);
  const dragCounter = useRef(0);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const toolMenuRef = useRef<HTMLDivElement>(null);
  const toolBtnRef = useRef<HTMLButtonElement>(null);
  const spaceMenuRef = useRef<HTMLDivElement>(null);
  const spaceBtnRef = useRef<HTMLButtonElement>(null);
  const kbMenuRef = useRef<HTMLDivElement>(null);
  const kbBtnRef = useRef<HTMLButtonElement>(null);
  const initialLoadRef = useRef(false);

  const activeCap = useMemo(
    () => getCapability(state.activeCapability),
    [state.activeCapability],
  );
  const isQuizMode = activeCap.value === "deep_question";
  const isMathAnimatorMode = activeCap.value === "math_animator";
  const isVisualizeMode = activeCap.value === "visualize";
  const isResearchMode = activeCap.value === "deep_research";
  const capabilityNeedsConfig =
    isQuizMode || isMathAnimatorMode || isVisualizeMode || isResearchMode;

  // Edit-invalidates-confirm wrappers — flipping any field after the user
  // hit *Confirm* should restore the gate so they re-confirm intentionally.
  // `useCallback` keeps identities stable so the memoized ChatComposer /
  // CapabilityConfigCard don't churn on every keystroke.
  const handleChangeQuizConfig = useCallback(
    (next: DeepQuestionFormConfig) => {
      setQuizConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
  const handleUploadQuizPdf = useCallback((file: File | null) => {
    setQuizPdf(file);
    setCapabilityConfigConfirmed(false);
  }, []);
  const handleChangeMathAnimatorConfig = useCallback(
    (next: MathAnimatorFormConfig) => {
      setMathAnimatorConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
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
  const selectedTools = useMemo(
    () => new Set(state.enabledTools),
    [state.enabledTools],
  );
  const hasMessages = state.messages.length > 0;
  const { ref: composerRef, height: composerHeight } =
    useMeasuredHeight<HTMLDivElement>();
  const visibleTools = useMemo(
    () => ALL_TOOLS.filter((t) => activeCap.allowedTools.includes(t.name)),
    [activeCap.allowedTools],
  );
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
  const historyReferencesPayload = useMemo(
    () => selectedHistorySessions.map((session) => session.sessionId),
    [selectedHistorySessions],
  );
  const questionNotebookReferencesPayload = useMemo(
    () => selectedQuestionEntries.map((entry) => entry.id),
    [selectedQuestionEntries],
  );
  const memoryReferencesPayload = useMemo(
    () => [...selectedMemoryFiles],
    [selectedMemoryFiles],
  );
  const chatSaveMessages = useMemo(
    () =>
      state.messages.map((msg) => ({
        role: msg.role,
        content: msg.content,
        capability: msg.capability,
      })),
    [state.messages],
  );
  const chatSavePayload = useMemo(() => {
    if (!state.messages.length) return null;
    const title =
      state.messages
        .find((msg) => msg.role === "user")
        ?.content.trim()
        .slice(0, 80) || "Chat Session";
    return {
      recordType: "chat" as const,
      title,
      // The actual transcript / userQuery are rebuilt inside SaveToNotebookModal
      // from the user's selected subset of messages. We still provide a
      // sensible fallback for non-selection callers.
      userQuery: "",
      output: "",
      metadata: {
        source: "chat",
        capability: state.activeCapability || "chat",
        ui_language: state.language,
        session_id: state.sessionId,
        total_message_count: state.messages.length,
      },
    };
  }, [state.activeCapability, state.language, state.messages, state.sessionId]);
  const lastMessage = state.messages[state.messages.length - 1];
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    shouldAutoScrollRef,
    handleScroll: handleMessagesScroll,
  } = useChatAutoScroll({
    hasMessages,
    isStreaming: state.isStreaming,
    composerHeight,
    messageCount: state.messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  });
  const copyAssistantMessage = useCallback(async (content: string) => {
    if (!content.trim()) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch (error) {
      console.error("Failed to copy assistant message:", error);
    }
  }, []);
  const handleAnswerNow = useCallback(
    (
      snapshot?: MessageRequestSnapshot,
      assistantMsg?: { content: string; events?: StreamEvent[] },
    ) => {
      if (!snapshot || !state.isStreaming) return;
      const answerNowEvents = (assistantMsg?.events ?? []).map((event) => ({
        type: event.type,
        stage: event.stage,
        content: event.content,
        metadata: event.metadata ?? {},
      }));
      cancelStreamingTurn();
      // Preserve the original capability — each capability now owns its
      // own answer-now fast-path (deep_solve jumps to writing,
      // deep_question to direct quiz synthesis, math_animator to
      // code-gen + render, etc.). The backend orchestrator only falls
      // back to ``chat`` if the requested capability is missing.
      const answerNowSnapshot: MessageRequestSnapshot = {
        ...snapshot,
        language: appLanguage,
        config: {
          ...(snapshot.config || {}),
          answer_now_context: {
            original_user_message: snapshot.content,
            partial_response: assistantMsg?.content || "",
            events: answerNowEvents,
          },
        },
      };
      window.setTimeout(() => {
        sendMessage(
          answerNowSnapshot.content,
          answerNowSnapshot.attachments,
          answerNowSnapshot.config,
          answerNowSnapshot.notebookReferences,
          answerNowSnapshot.historyReferences,
          {
            displayUserMessage: false,
            persistUserMessage: false,
            requestSnapshotOverride: answerNowSnapshot,
            bookReferences: answerNowSnapshot.bookReferences,
          },
          answerNowSnapshot.questionNotebookReferences,
          answerNowSnapshot.skills,
          answerNowSnapshot.memoryReferences,
        );
        shouldAutoScrollRef.current = true;
      }, 0);
    },
    [
      appLanguage,
      cancelStreamingTurn,
      sendMessage,
      shouldAutoScrollRef,
      state.isStreaming,
    ],
  );

  /* ---- URL-driven session loading ---- */
  useEffect(() => {
    if (initialLoadRef.current) return;
    initialLoadRef.current = true;
    if (sessionIdParam) {
      void loadSession(sessionIdParam).catch(() => {
        router.replace("/chat", { scroll: false });
      });
    } else {
      newSession();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // When URL param changes (sidebar navigation), load the corresponding session
  const prevSessionIdParam = useRef(sessionIdParam);
  useEffect(() => {
    if (sessionIdParam === prevSessionIdParam.current) return;
    prevSessionIdParam.current = sessionIdParam;
    if (sessionIdParam) {
      if (sessionIdParam === state.sessionId) return;
      void loadSession(sessionIdParam).catch(() => {
        router.replace("/chat", { scroll: false });
      });
    } else {
      newSession();
    }
  }, [sessionIdParam, loadSession, newSession, router, state.sessionId]);

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
      } catch {
        setKnowledgeBases([]);
      }
    },
    [],
  );

  /* Load KBs */
  useEffect(() => {
    void refreshKnowledgeBases({ force: true });
  }, [refreshKnowledgeBases]);

  const refreshLLMOptions = useCallback(async () => {
    setLLMOptionsLoading(true);
    try {
      const payload = await listLLMOptions();
      setLLMOptions(payload.options);
      setActiveLLMDefault(payload.active);
      setLLMOptionsError(false);
    } catch {
      setLLMOptionsError(true);
      setLLMOptions([]);
      setActiveLLMDefault(null);
    } finally {
      setLLMOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshLLMOptions();
  }, [refreshLLMOptions]);

  useEffect(() => {
    if (state.llmSelection || !activeLLMDefault) return;
    setLLMSelection(activeLLMDefault);
  }, [activeLLMDefault, setLLMSelection, state.llmSelection]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const refresh = () => {
      void refreshKnowledgeBases({ force: true });
      void refreshLLMOptions();
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
  }, [refreshKnowledgeBases, refreshLLMOptions]);

  useEffect(() => {
    setCapabilityConfigs(loadCapabilityPlaygroundConfigs());
  }, []);

  /* URL query params (capability, tool) */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const p = new URLSearchParams(window.location.search);
    const qc = p.get("capability");
    const qt = p.getAll("tool");
    if (qc !== null) handleSelectCapability(qc || "");
    else if (qt.length) {
      const valid = qt.filter((t): t is ToolName =>
        ALL_TOOLS.some((d) => d.name === t),
      );
      if (valid.length) setTools(Array.from(new Set(valid)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        toolMenuRef.current &&
        !toolMenuRef.current.contains(t) &&
        toolBtnRef.current &&
        !toolBtnRef.current.contains(t)
      )
        setToolMenuOpen(false);
      if (
        spaceMenuRef.current &&
        !spaceMenuRef.current.contains(t) &&
        spaceBtnRef.current &&
        !spaceBtnRef.current.contains(t)
      )
        setSpaceMenuOpen(false);
      if (
        kbMenuRef.current &&
        !kbMenuRef.current.contains(t) &&
        kbBtnRef.current &&
        !kbBtnRef.current.contains(t)
      )
        setKbMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const allowed = new Set(visibleTools.map((tool) => tool.name));
    const nextTools = state.enabledTools.filter((tool) =>
      allowed.has(tool as ToolName),
    );
    if (nextTools.length !== state.enabledTools.length) setTools(nextTools);
  }, [setTools, state.enabledTools, visibleTools]);

  /* ---- handlers ---- */

  const handleSelectCapability = useCallback(
    (value: string) => {
      const cap =
        CAPABILITIES.find((c) => c.value === value) ?? CAPABILITIES[0];
      const storageKey = cap.value || "chat";
      const config = resolveCapabilityPlaygroundConfig(
        capabilityConfigs,
        storageKey,
        cap.allowedTools,
      );
      setCapability(cap.value || null);
      setTools(
        config.enabledTools.length > 0 || capabilityConfigs[storageKey]
          ? [...config.enabledTools]
          : [...cap.defaultTools],
      );
      if (config.knowledgeBase) setKBs([config.knowledgeBase]);
      // Switching capability invalidates any prior config confirmation —
      // the new capability has its own form that needs explicit confirm.
      setCapabilityConfigConfirmed(false);
      setCapMenuOpen(false);
    },
    [capabilityConfigs, setCapability, setKBs, setTools],
  );

  const toggleTool = useCallback(
    (tool: string) => {
      if (!activeCap.allowedTools.includes(tool as ToolName)) return;
      if (selectedTools.has(tool)) {
        setTools(state.enabledTools.filter((t) => t !== tool));
      } else {
        setTools([...state.enabledTools, tool]);
      }
    },
    [activeCap.allowedTools, selectedTools, setTools, state.enabledTools],
  );

  const toggleResearchSource = useCallback((source: ResearchSource) => {
    setResearchConfig((current) => ({
      ...current,
      sources: current.sources.includes(source)
        ? current.sources.filter((item) => item !== source)
        : [...current.sources, source],
    }));
    // Toggling sources is part of the Research config — invalidate the
    // confirm so the user can re-verify before sending.
    setCapabilityConfigConfirmed(false);
  }, []);

  const fileToAttachment = useCallback(
    (f: File): Promise<PendingAttachment> =>
      new Promise((resolve, reject) => {
        readFileAsDataUrl(f)
          .then((raw) => {
            // SVG: treat as file (text extraction on server, vision models
            // reject SVG) but keep the data URL so the chip can render a
            // thumbnail via a raw <img> tag.
            const svg = isSvgFilename(f.name) || f.type === "image/svg+xml";
            const isImage = !svg && f.type.startsWith("image/");
            const b64 = extractBase64FromDataUrl(raw);
            resolve({
              type: isImage ? "image" : "file",
              filename: f.name,
              base64: b64,
              previewUrl: isImage || svg ? raw : undefined,
              size: f.size,
              mimeType: f.type || undefined,
            });
          })
          .catch(reject);
      }),
    [],
  );

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
      let runningTotal = attachments.reduce((s, a) => s + (a.size ?? 0), 0);
      const accepted: File[] = [];
      const rejected: {
        name: string;
        reason: "unsupported" | "too_large" | "quota";
      }[] = [];
      for (const f of files) {
        const kind = classifyFile(f);
        if (!kind) {
          rejected.push({ name: f.name, reason: "unsupported" });
          continue;
        }
        if (f.size > MAX_ATTACHMENT_BYTES) {
          rejected.push({ name: f.name, reason: "too_large" });
          continue;
        }
        if (runningTotal + f.size > MAX_TOTAL_ATTACHMENT_BYTES) {
          rejected.push({ name: f.name, reason: "quota" });
          break;
        }
        runningTotal += f.size;
        accepted.push(f);
      }
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
    [attachments, showAttachmentError, t],
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
    () => buildSessionActivity(state.messages),
    [state.messages],
  );

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
          canConfirm
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
    if (isMathAnimatorMode) {
      return (
        <CapabilityConfigCard
          capability="math_animator"
          confirmed={capabilityConfigConfirmed}
          canConfirm
          onConfirm={handleConfirmCapabilityConfig}
        >
          <MathAnimatorConfigPanel
            value={mathAnimatorConfig}
            onChange={handleChangeMathAnimatorConfig}
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
    isMathAnimatorMode,
    isVisualizeMode,
    capabilityConfigConfirmed,
    handleConfirmCapabilityConfig,
    quizConfig,
    quizPdf,
    handleChangeQuizConfig,
    handleUploadQuizPdf,
    mathAnimatorConfig,
    handleChangeMathAnimatorConfig,
    visualizeConfig,
    handleChangeVisualizeConfig,
    researchConfig,
    researchValidation.errors,
    handleChangeResearchConfig,
  ]);

  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null);
  // Clicking an attachment (from the Activity panel or from a chat message)
  // routes into the Viewer panel as a new file tab. The viewer auto-opens
  // and the preference is persisted so a follow-up click feels instant.
  const handlePreviewMessageAttachment = useCallback(
    (a: MessageAttachment) => {
      viewerPanelRef.current?.openFileTab(a);
    },
    [],
  );

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

  const handleSend = useCallback(
    async (content: string) => {
      if (
        (!content &&
          !attachments.length &&
          !selectedBookReferences.length &&
          !selectedNotebookRecords.length &&
          !selectedHistorySessions.length &&
          !selectedQuestionEntries.length &&
          !selectedSkills.length &&
          !skillsAutoMode &&
          !selectedMemoryFiles.length) ||
        state.isStreaming
      )
        return;

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
      if (isMathAnimatorMode)
        config = buildMathAnimatorWSConfig(mathAnimatorConfig);
      if (isVisualizeMode) config = buildVisualizeWSConfig(visualizeConfig);
      if (isResearchMode) config = buildResearchWSConfig(researchConfig);

      const retrievalSelection =
        activeCap.value === ""
          ? applyChatRetrievalMode(
              state.enabledTools,
              state.knowledgeBases,
              chatRetrievalMode,
            )
          : {
              enabledTools: [...state.enabledTools],
              knowledgeBases: [...state.knowledgeBases],
            };

      const skillsPayload = skillsAutoMode ? ["auto"] : [...selectedSkills];
      const memoryPayload = [...memoryReferencesPayload];
      const messageContent =
        content ||
        (selectedNotebookRecords.length ||
        selectedBookReferences.length ||
        selectedHistorySessions.length ||
        selectedQuestionEntries.length ||
        skillsPayload.length ||
        memoryPayload.length
          ? t("Please use the selected context to help with this request.")
          : "") ||
        (isMathAnimatorMode
          ? attachments.some((a) => a.type === "image")
            ? t(
                "Generate a math animation from the attached reference image(s).",
              )
            : ""
          : attachments.some((a) => a.type === "image")
            ? t("Please analyze the attached image(s).")
            : "");
      sendMessage(
        messageContent,
        extraAttachments,
        config,
        notebookReferencesPayload,
        historyReferencesPayload,
        {
          bookReferences: bookReferencesPayload,
          requestSnapshotOverride: {
            content: messageContent,
            capability: state.activeCapability,
            enabledTools: retrievalSelection.enabledTools,
            knowledgeBases: retrievalSelection.knowledgeBases,
            language: state.language,
            ...(extraAttachments.length
              ? { attachments: extraAttachments }
              : {}),
            ...(config && Object.keys(config).length > 0 ? { config } : {}),
            ...(notebookReferencesPayload.length
              ? { notebookReferences: notebookReferencesPayload }
              : {}),
            ...(historyReferencesPayload.length
              ? { historyReferences: historyReferencesPayload }
              : {}),
            ...(questionNotebookReferencesPayload.length
              ? {
                  questionNotebookReferences:
                    questionNotebookReferencesPayload,
                }
              : {}),
            ...(bookReferencesPayload.length
              ? { bookReferences: bookReferencesPayload }
              : {}),
            ...(skillsPayload.length ? { skills: skillsPayload } : {}),
            ...(memoryPayload.length
              ? { memoryReferences: memoryPayload }
              : {}),
            ...(state.llmSelection
              ? { llmSelection: state.llmSelection }
              : {}),
          },
        },
        questionNotebookReferencesPayload,
        skillsPayload,
        memoryPayload,
      );
      shouldAutoScrollRef.current = true;
      setAttachments([]);
      setSelectedBookReferences([]);
      setSelectedNotebookRecords([]);
      setSelectedHistorySessions([]);
      setSelectedQuestionEntries([]);
      setSelectedSkills([]);
      setSkillsAutoMode(false);
      setSelectedMemoryFiles([]);
    },
    [
      attachments,
      activeCap.value,
      bookReferencesPayload,
      historyReferencesPayload,
      isMathAnimatorMode,
      isQuizMode,
      isResearchMode,
      isVisualizeMode,
      mathAnimatorConfig,
      memoryReferencesPayload,
      notebookReferencesPayload,
      chatRetrievalMode,
      questionNotebookReferencesPayload,
      quizConfig,
      quizPdf,
      researchConfig,
      selectedHistorySessions.length,
      selectedMemoryFiles.length,
      selectedBookReferences.length,
      selectedNotebookRecords.length,
      selectedQuestionEntries.length,
      selectedSkills,
      skillsAutoMode,
      sendMessage,
      shouldAutoScrollRef,
      state.activeCapability,
      state.enabledTools,
      state.knowledgeBases,
      state.isStreaming,
      state.language,
      state.llmSelection,
      t,
      visualizeConfig,
    ],
  );

  const handleConfirmOutline = useCallback(
    (
      outline: OutlineItem[],
      _topic: string,
      originalConfig?: Record<string, unknown> | null,
    ) => {
      const config: Record<string, unknown> = {
        ...(originalConfig ?? {
          mode: researchConfig.mode,
          depth: researchConfig.depth,
          sources: [...researchConfig.sources],
        }),
        confirmed_outline: outline,
      };
      sendMessage(_topic, [], config, undefined, undefined, {
        displayUserMessage: false,
        persistUserMessage: false,
      });
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
      setKBs(
        current.includes(name)
          ? current.filter((kb) => kb !== name)
          : [...current, name],
      );
    },
    [setKBs, state.knowledgeBases],
  );
  const handleSelectNotebookPicker = useCallback(() => {
    setShowNotebookPicker(true);
  }, []);
  const handleSelectBookPicker = useCallback(() => {
    setShowBookPicker(true);
  }, []);
  const handleSelectHistoryPicker = useCallback(() => {
    setShowHistoryPicker(true);
  }, []);
  const handleSelectQuestionBankPicker = useCallback(() => {
    setShowQuestionBankPicker(true);
  }, []);
  const handleSelectSkillsPicker = useCallback(() => {
    setShowSkillsPicker(true);
  }, []);
  const handleSelectMemoryPicker = useCallback(() => {
    setShowMemoryPicker(true);
  }, []);
  const handleRemoveHistory = useCallback((sessionId: string) => {
    setSelectedHistorySessions((prev) =>
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
  const handleRemoveQuestion = useCallback((entryId: number) => {
    setSelectedQuestionEntries((prev) =>
      prev.filter((entry) => entry.id !== entryId),
    );
  }, []);
  const handleToggleSkill = useCallback((name: string) => {
    setSkillsAutoMode(false);
    setSelectedSkills((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }, []);

  const handleSetSkillsAuto = useCallback((auto: boolean) => {
    setSkillsAutoMode(auto);
    if (auto) setSelectedSkills([]);
  }, []);

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
  const handleApplyBookReferences = useCallback(
    (references: SelectedBookReference[]) => {
      setSelectedBookReferences(references);
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
  const handleCloseQuestionBankPicker = useCallback(() => {
    setShowQuestionBankPicker(false);
  }, []);
  const handleApplyQuestionEntries = useCallback(
    (entries: SelectedQuestionEntry[]) => {
      setSelectedQuestionEntries(entries);
    },
    [],
  );
  const handleCloseSkillsPicker = useCallback(() => {
    setShowSkillsPicker(false);
  }, []);
  const handleApplySkillsSelection = useCallback(
    (selection: { auto: boolean; skills: string[] }) => {
      setSkillsAutoMode(selection.auto);
      setSelectedSkills(selection.auto ? [] : selection.skills);
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

  const handleNewChat = useCallback(() => {
    router.push("/chat");
  }, [router]);

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
    <div
      // When the preview drawer is open AND the viewport is wide enough,
      // push the chat content to the left by the drawer's width so the two
      // panels live side-by-side (matches Claude desktop). On smaller
      // screens the drawer overlays — squeezing a phone-width chat into
      // the remaining ~30 px would be useless. The actual padding +
      // transition lives in `chat-preview-shell` (globals.css) so we can
      // hand-tune it without fighting Tailwind's arbitrary-value parser.
      data-preview-open={previewSource ? "true" : "false"}
      data-activity-open={activityPanelOpen ? "true" : "false"}
      data-viewer-open={viewerPanelOpen ? "true" : "false"}
      className="chat-preview-shell flex h-full flex-col overflow-hidden bg-[var(--background)]"
    >
      <div
        ref={headerRef}
        className="mx-auto flex w-full max-w-[960px] flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-6 pt-3 pb-0"
      >
        <span className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
          {t(activeCap.label)}
        </span>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <HeaderActionButton
            compact={headerCompact}
            onClick={() => setShowSaveModal(true)}
            disabled={!chatSavePayload}
            icon={BookmarkPlus}
            label={t("Save to Notebook")}
          />
          <HeaderActionButton
            compact={headerCompact}
            onClick={handleDownloadMarkdown}
            disabled={!state.messages.length}
            icon={Download}
            label={t("Download Markdown")}
            title={t("Download chat history as Markdown")}
          />
          <HeaderActionButton
            compact={headerCompact}
            onClick={handleNewChat}
            icon={SquarePen}
            label={t("New chat")}
          />
          <HeaderActionButton
            compact={headerCompact}
            onClick={toggleActivityPanel}
            active={activityPanelOpen}
            icon={PanelRight}
            label={t("Activity")}
            title={t("Session activity")}
          />
          <HeaderActionButton
            compact={headerCompact}
            onClick={toggleViewerPanel}
            active={viewerPanelOpen}
            icon={BookOpen}
            label={t("Viewer")}
            title={t("Open viewer")}
          />
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-[960px] flex-1 min-h-0 flex-col overflow-hidden px-6">
        {!hasMessages ? (
          <div className="flex flex-1 min-h-0 flex-col items-center justify-center animate-fade-in">
            <div className="text-center">
              <h1 className="font-serif text-[36px] font-medium tracking-[-0.01em] text-[var(--foreground)]">
                {t("What would you like to learn?")}
              </h1>
              <p className="mt-4 text-[15px] text-[var(--muted-foreground)]">
                {t("Ask anything — I'm here to help you understand.")}
              </p>
            </div>
          </div>
        ) : (
          <div
            ref={messagesContainerRef}
            data-chat-scroll-root="true"
            onScroll={handleMessagesScroll}
            onClick={handleMessagesClick}
            className={`mx-auto w-full flex-1 min-h-0 space-y-7 overflow-y-auto pr-4 [scrollbar-gutter:stable] ${hasMessages ? "pt-6" : "pt-2 pb-6"}`}
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
            <ChatMessageList
              messages={state.messages}
              isStreaming={state.isStreaming}
              sessionId={state.sessionId}
              language={state.language}
              onAnswerNow={handleAnswerNow}
              onCopyAssistantMessage={copyAssistantMessage}
              onRegenerateMessage={handleRegenerateMessage}
              onConfirmOutline={handleConfirmOutline}
              onPreviewAttachment={handlePreviewMessageAttachment}
              onDeleteTurn={deleteTurn}
              selectedBranches={state.selectedBranches}
              onEditMessage={editMessage}
              onSwitchBranch={switchBranch}
            />
            <div ref={messagesEndRef} className="h-px w-full shrink-0" />
          </div>
        )}

        <ChatComposer
          composerRef={composerRef}
          capMenuRef={capMenuRef}
          capBtnRef={capBtnRef}
          toolMenuRef={toolMenuRef}
          toolBtnRef={toolBtnRef}
          spaceMenuRef={spaceMenuRef}
          spaceBtnRef={spaceBtnRef}
          kbMenuRef={kbMenuRef}
          kbBtnRef={kbBtnRef}
          dragCounter={dragCounter}
          dragging={dragging}
          capMenuOpen={capMenuOpen}
          toolMenuOpen={toolMenuOpen}
          spaceMenuOpen={spaceMenuOpen}
          kbMenuOpen={kbMenuOpen}
          hasMessages={hasMessages}
          attachments={attachments}
          attachmentError={attachmentError}
          activeCap={activeCap}
          visibleTools={visibleTools}
          selectedTools={selectedTools}
          knowledgeBases={knowledgeBases}
          llmOptions={llmOptions}
          activeLLMDefault={activeLLMDefault}
          llmSelection={state.llmSelection}
          llmOptionsLoading={llmOptionsLoading}
          llmOptionsError={llmOptionsError}
          selectedBookReferences={selectedBookReferences}
          selectedNotebookRecords={selectedNotebookRecords}
          selectedHistorySessions={selectedHistorySessions}
          selectedQuestionEntries={selectedQuestionEntries}
          notebookReferenceGroups={notebookReferenceGroups}
          selectedSkills={selectedSkills}
          skillsAutoMode={skillsAutoMode}
          selectedMemoryFiles={selectedMemoryFiles}
          selectedKnowledgeBases={state.knowledgeBases}
          isStreaming={state.isStreaming}
          isResearchMode={isResearchMode}
          isMathAnimatorMode={isMathAnimatorMode}
          isVisualizeMode={isVisualizeMode}
          isAutoMode={false}
          autoEnabledCaps={EMPTY_SET}
          researchConfigSources={researchConfig.sources}
          capabilityNeedsConfig={capabilityNeedsConfig}
          capabilityConfigConfirmed={capabilityConfigConfirmed}
          onRequestConfigConfirm={ensureActivityPanelOpen}
          capabilities={CAPABILITIES}
          researchSources={RESEARCH_SOURCES}
          onSetCapMenuOpen={setCapMenuOpen}
          onSetToolMenuOpen={setToolMenuOpen}
          onSetSpaceMenuOpen={setSpaceMenuOpen}
          onSetKbMenuOpen={setKbMenuOpen}
          chatRetrievalMode={chatRetrievalMode}
          onSetChatRetrievalMode={setChatRetrievalMode}
          onToggleAutoCap={noopToggleAutoCap}
          onToggleKB={handleToggleKB}
          onSelectLLM={setLLMSelection}
          onSelectNotebookPicker={handleSelectNotebookPicker}
          onSelectBookPicker={handleSelectBookPicker}
          onSelectHistoryPicker={handleSelectHistoryPicker}
          onSelectQuestionBankPicker={handleSelectQuestionBankPicker}
          onSelectSkillsPicker={handleSelectSkillsPicker}
          onSelectMemoryPicker={handleSelectMemoryPicker}
          onToggleTool={toggleTool}
          onToggleSkill={handleToggleSkill}
          onSetSkillsAuto={handleSetSkillsAuto}
          onToggleMemoryFile={handleToggleMemoryFile}
          onToggleResearchSource={toggleResearchSource}
          onSend={handleSend}
          onRemoveAttachment={removeAttachment}
          onPreviewAttachment={handlePreviewPendingAttachment}
          onRemoveHistory={handleRemoveHistory}
          onRemoveBookReference={handleRemoveBookReference}
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
      <HistorySessionPicker
        open={showHistoryPicker}
        onClose={handleCloseHistoryPicker}
        onApply={handleApplyHistorySessions}
      />
      <QuestionBankPicker
        open={showQuestionBankPicker}
        onClose={handleCloseQuestionBankPicker}
        onApply={handleApplyQuestionEntries}
      />
      <SkillsPicker
        open={showSkillsPicker}
        initialAuto={skillsAutoMode}
        initialSkills={selectedSkills}
        onClose={handleCloseSkillsPicker}
        onApply={handleApplySkillsSelection}
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
      <SessionActivityPanel
        open={activityPanelOpen && previewSource === null && !viewerPanelOpen}
        activity={sessionActivity}
        onOpenAttachment={handlePreviewMessageAttachment}
        configSection={capabilityConfigSection}
      />
      <SessionViewerPanel
        ref={viewerPanelRef}
        open={viewerPanelOpen && previewSource === null}
        sessionId={state.sessionId}
        onClose={() => setViewerOpen(false)}
        onAutoOpen={() => setViewerOpen(true)}
      />
    </div>
  );
}

/**
 * Header action button that auto-collapses to icon-only when the chat
 * column gets squeezed (Viewer panel open, narrow viewport, etc.). The
 * label stays as the button's `title` so hovering an icon still reveals
 * what it does. Optional `active` flag paints the button with a primary
 * tint, used by the panel-toggle buttons to surface their on/off state.
 */
function HeaderActionButton({
  compact,
  onClick,
  disabled,
  active,
  icon: Icon,
  label,
  title,
}: {
  compact: boolean;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  icon: LucideIcon;
  label: string;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      aria-label={label}
      aria-pressed={active}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg border text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        compact ? "px-2 py-1.5" : "px-3 py-1.5"
      } ${
        active
          ? "border-[var(--primary)]/40 bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))] text-[var(--primary)] hover:border-[var(--primary)]/55"
          : "border-[var(--border)]/50 text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)]"
      }`}
    >
      <Icon size={14} strokeWidth={1.7} className="shrink-0" />
      {compact ? null : <span>{label}</span>}
    </button>
  );
}
