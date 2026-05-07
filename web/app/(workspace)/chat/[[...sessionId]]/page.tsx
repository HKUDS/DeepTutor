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

/* ------------------------------------------------------------------ */
/*  Type & data definitions                                           */
/* ------------------------------------------------------------------ */

type ToolName =
  | "brainstorm"
  | "rag"
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
  { name: "rag", label: "RAG", icon: Database },
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
      "rag",
      "web_search",
      "code_execution",
      "reason",
      "paper_search",
    ],
    defaultTools: [],
  },
  {
    value: "deep_solve",
    label: "Deep Solve",
    description: "Multi-step reasoning & problem solving",
    icon: BrainCircuit,
    allowedTools: ["rag", "web_search", "code_execution", "reason"],
    defaultTools: ["rag", "web_search", "code_execution", "reason"],
  },
  {
    value: "deep_question",
    label: "Quiz Generation",
    description: "Auto-validated question generation",
    icon: PenLine,
    allowedTools: ["rag", "web_search", "code_execution"],
    defaultTools: ["rag", "web_search", "code_execution"],
  },
  {
    value: "deep_research",
    label: "Deep Research",
    description: "Comprehensive multi-agent research",
    icon: Microscope,
    allowedTools: [],
    defaultTools: [],
  },
  {
    value: "math_animator",
    label: "Math Animator",
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
  // Unified collapse state for the capability-specific config panel
  // (Quiz / Math Animator / Visualize / Deep Research). Default collapsed so
  // a fresh Chat / Deep Solve session has the shortest possible composer.
  const [panelCollapsed, setPanelCollapsed] = useState(true);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [showBookPicker, setShowBookPicker] = useState(false);
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showQuestionBankPicker, setShowQuestionBankPicker] = useState(false);
  const [showSkillsPicker, setShowSkillsPicker] = useState(false);
  const [showMemoryPicker, setShowMemoryPicker] = useState(false);
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [spaceMenuOpen, setSpaceMenuOpen] = useState(false);
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
  const initialLoadRef = useRef(false);

  const activeCap = useMemo(
    () => getCapability(state.activeCapability),
    [state.activeCapability],
  );
  const isQuizMode = activeCap.value === "deep_question";
  const isMathAnimatorMode = activeCap.value === "math_animator";
  const isVisualizeMode = activeCap.value === "visualize";
  const isResearchMode = activeCap.value === "deep_research";
  const selectedTools = useMemo(
    () => new Set(state.enabledTools),
    [state.enabledTools],
  );
  const ragActive = isResearchMode
    ? researchConfig.sources.includes("kb")
    : selectedTools.has("rag");
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
        if (!state.knowledgeBases.length && list.length) {
          const def = list.find((k: KnowledgeBase) => k.is_default);
          setKBs([def?.name || list[0].name]);
        }
      } catch {
        setKnowledgeBases([]);
      }
    },
    [setKBs, state.knowledgeBases.length],
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
      if (config.enabledTools.includes("rag") && config.knowledgeBase)
        setKBs([config.knowledgeBase]);
      // Default-expand the per-capability settings panel right after a
      // capability switch so users immediately see the form. Sending a
      // message later will auto-collapse it (see handleSend).
      setPanelCollapsed(false);
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

  const handlePreviewMessageAttachment = useCallback((a: MessageAttachment) => {
    setPreviewSource({
      filename: a.filename || "",
      mimeType: a.mime_type,
      type: a.type,
      url: a.url,
      base64: a.base64,
      extractedText: a.extracted_text,
      id: a.id,
    });
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
        { bookReferences: bookReferencesPayload },
        questionNotebookReferencesPayload,
        skillsPayload,
        memoryPayload,
      );
      shouldAutoScrollRef.current = true;
      // Auto-collapse the per-capability settings panel after sending so the
      // composer stays compact during conversation.
      setPanelCollapsed(true);
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
      bookReferencesPayload,
      historyReferencesPayload,
      isMathAnimatorMode,
      isQuizMode,
      isResearchMode,
      isVisualizeMode,
      mathAnimatorConfig,
      memoryReferencesPayload,
      notebookReferencesPayload,
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
      state.isStreaming,
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

  const handleSetKB = useCallback(
    (kb: string) => {
      setKBs(kb ? [kb] : []);
    },
    [setKBs],
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

  const handleTogglePanelCollapsed = useCallback(() => {
    setPanelCollapsed((prev) => !prev);
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
      className="chat-preview-shell flex h-full flex-col overflow-hidden bg-[var(--background)]"
    >
      <div className="mx-auto flex w-full items-center justify-between px-6 pt-3 pb-0">
        <span className="text-[15px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
          {t(activeCap.label)}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSaveModal(true)}
            disabled={!chatSavePayload}
            className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)]"
          >
            {t("Save to Notebook")}
          </button>
          <button
            onClick={handleDownloadMarkdown}
            disabled={!state.messages.length}
            title={t("Download chat history as Markdown")}
            className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)]"
          >
            {t("Download Markdown")}
          </button>
          <button
            onClick={handleNewChat}
            className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
          >
            {t("New chat")}
          </button>
        </div>
      </div>
      <div className="mx-auto flex w-full flex-1 min-h-0 flex-col overflow-hidden px-6">
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
            className={`mx-auto w-full flex-1 min-h-0 space-y-7 overflow-y-auto pr-4 [scrollbar-gutter:stable] ${hasMessages ? "pt-0" : "pt-2 pb-6"}`}
            style={
              hasMessages
                ? (() => {
                    const maskImage =
                      "linear-gradient(to bottom, transparent 0px, #000 32px, #000 calc(100% - 40px), transparent 100%)";
                    return {
                      paddingBottom: "4px",
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
          dragCounter={dragCounter}
          dragging={dragging}
          capMenuOpen={capMenuOpen}
          toolMenuOpen={toolMenuOpen}
          spaceMenuOpen={spaceMenuOpen}
          hasMessages={hasMessages}
          attachments={attachments}
          attachmentError={attachmentError}
          activeCap={activeCap}
          visibleTools={visibleTools}
          selectedTools={selectedTools}
          ragActive={ragActive}
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
          stateKnowledgeBase={state.knowledgeBases[0] || ""}
          isStreaming={state.isStreaming}
          isResearchMode={isResearchMode}
          isQuizMode={isQuizMode}
          isMathAnimatorMode={isMathAnimatorMode}
          isVisualizeMode={isVisualizeMode}
          quizConfig={quizConfig}
          quizPdf={quizPdf}
          mathAnimatorConfig={mathAnimatorConfig}
          visualizeConfig={visualizeConfig}
          researchConfig={researchConfig}
          researchValidationErrors={researchValidation.errors}
          panelCollapsed={panelCollapsed}
          capabilities={CAPABILITIES}
          researchSources={RESEARCH_SOURCES}
          onSetCapMenuOpen={setCapMenuOpen}
          onSetToolMenuOpen={setToolMenuOpen}
          onSetSpaceMenuOpen={setSpaceMenuOpen}
          onSetKB={handleSetKB}
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
          onChangeQuizConfig={setQuizConfig}
          onUploadQuizPdf={setQuizPdf}
          onChangeMathAnimatorConfig={setMathAnimatorConfig}
          onChangeVisualizeConfig={setVisualizeConfig}
          onChangeResearchConfig={setResearchConfig}
          onTogglePanelCollapsed={handleTogglePanelCollapsed}
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
    </div>
  );
}
