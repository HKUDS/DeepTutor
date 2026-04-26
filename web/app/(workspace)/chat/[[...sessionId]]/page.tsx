"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  BarChart3,
  BookOpen,
  BrainCircuit,
  Clapperboard,
  Code2,
  Database,
  Download,
  FileSearch,
  Globe,
  Lightbulb,
  MessageSquare,
  Microscope,
  PenLine,
  Plus,
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
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import type { StreamEvent } from "@/lib/unified-ws";
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
import { listSkills, type SkillInfo } from "@/lib/skills-api";
import { downloadChatMarkdown } from "@/lib/chat-export";

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

  const {
    state,
    setTools,
    setCapability,
    setKBs,
    sendMessage,
    cancelStreamingTurn,
    regenerateLastMessage,
    newSession,
    loadSession,
  } = useUnifiedChat();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [capabilityConfigs, setCapabilityConfigs] =
    useState<CapabilityPlaygroundConfigMap>({});
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [previewSource, setPreviewSource] = useState<FilePreviewSource | null>(
    null,
  );
  const attachmentErrorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
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
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showQuestionBankPicker, setShowQuestionBankPicker] = useState(false);
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [refMenuOpen, setRefMenuOpen] = useState(false);
  const [skillMenuOpen, setSkillMenuOpen] = useState(false);
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<
    SelectedRecord[]
  >([]);
  const [selectedHistorySessions, setSelectedHistorySessions] = useState<
    SelectedHistorySession[]
  >([]);
  const [selectedQuestionEntries, setSelectedQuestionEntries] = useState<
    SelectedQuestionEntry[]
  >([]);
  const [availableSkills, setAvailableSkills] = useState<SkillInfo[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [skillsAutoMode, setSkillsAutoMode] = useState(false);
  const dragCounter = useRef(0);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const toolMenuRef = useRef<HTMLDivElement>(null);
  const toolBtnRef = useRef<HTMLButtonElement>(null);
  const refMenuRef = useRef<HTMLDivElement>(null);
  const refBtnRef = useRef<HTMLButtonElement>(null);
  const skillMenuRef = useRef<HTMLDivElement>(null);
  const skillBtnRef = useRef<HTMLButtonElement>(null);
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
  const historyReferencesPayload = useMemo(
    () => selectedHistorySessions.map((session) => session.sessionId),
    [selectedHistorySessions],
  );
  const questionNotebookReferencesPayload = useMemo(
    () => selectedQuestionEntries.map((entry) => entry.id),
    [selectedQuestionEntries],
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
          },
          answerNowSnapshot.questionNotebookReferences,
        );
        shouldAutoScrollRef.current = true;
      }, 0);
    },
    [cancelStreamingTurn, sendMessage, shouldAutoScrollRef, state.isStreaming],
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
      void loadSession(sessionIdParam).catch(() => {
        router.replace("/chat", { scroll: false });
      });
    } else {
      newSession();
    }
  }, [sessionIdParam, loadSession, newSession, router]);

  // When a new session_id is assigned by the server, update the URL
  useEffect(() => {
    if (state.sessionId && !sessionIdParam) {
      router.replace(`/chat/${state.sessionId}`, { scroll: false });
    }
  }, [state.sessionId, sessionIdParam, router]);

  /* Load KBs */
  useEffect(() => {
    (async () => {
      try {
        const list = await listKnowledgeBases();
        setKnowledgeBases(list);
        if (!state.knowledgeBases.length && list.length) {
          const def = list.find((k: KnowledgeBase) => k.is_default);
          setKBs([def?.name || list[0].name]);
        }
      } catch {
        setKnowledgeBases([]);
      }
    })();
  }, [setKBs, state.knowledgeBases.length]);

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
        refMenuRef.current &&
        !refMenuRef.current.contains(t) &&
        refBtnRef.current &&
        !refBtnRef.current.contains(t)
      )
        setRefMenuOpen(false);
      if (
        skillMenuRef.current &&
        !skillMenuRef.current.contains(t) &&
        skillBtnRef.current &&
        !skillBtnRef.current.contains(t)
      )
        setSkillMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    listSkills()
      .then((items) => {
        if (!cancelled) setAvailableSkills(items);
      })
      .catch(() => {
        if (!cancelled) setAvailableSkills([]);
      });
    return () => {
      cancelled = true;
    };
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

  const handlePreviewMessageAttachment = useCallback(
    (a: MessageAttachment) => {
      setPreviewSource({
        filename: a.filename || "",
        mimeType: a.mime_type,
        type: a.type,
        url: a.url,
        base64: a.base64,
        extractedText: a.extracted_text,
        id: a.id,
      });
    },
    [],
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

  const handleSend = useCallback(
    async (content: string) => {
      if (
        (!content &&
          !attachments.length &&
          !selectedNotebookRecords.length &&
          !selectedHistorySessions.length &&
          !selectedQuestionEntries.length) ||
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

      const isChatMode = !state.activeCapability;
      const skillsPayload = isChatMode
        ? skillsAutoMode
          ? ["auto"]
          : selectedSkills
        : undefined;
      sendMessage(
        content ||
          (selectedNotebookRecords.length ||
          selectedHistorySessions.length ||
          selectedQuestionEntries.length
            ? "Please use the selected context to help with this request."
            : "") ||
          (isMathAnimatorMode
            ? attachments.some((a) => a.type === "image")
              ? "Generate a math animation from the attached reference image(s)."
              : ""
            : attachments.some((a) => a.type === "image")
              ? "Please analyze the attached image(s)."
              : ""),
        extraAttachments,
        config,
        notebookReferencesPayload,
        historyReferencesPayload,
        undefined,
        questionNotebookReferencesPayload,
        skillsPayload,
      );
      shouldAutoScrollRef.current = true;
      // Auto-collapse the per-capability settings panel after sending so the
      // composer stays compact during conversation.
      setPanelCollapsed(true);
      setAttachments([]);
      setSelectedNotebookRecords([]);
      setSelectedHistorySessions([]);
      setSelectedQuestionEntries([]);
    },
    [
      attachments,
      historyReferencesPayload,
      isMathAnimatorMode,
      isQuizMode,
      isResearchMode,
      isVisualizeMode,
      mathAnimatorConfig,
      notebookReferencesPayload,
      questionNotebookReferencesPayload,
      quizConfig,
      quizPdf,
      researchConfig,
      selectedHistorySessions.length,
      selectedNotebookRecords.length,
      selectedQuestionEntries.length,
      selectedSkills,
      skillsAutoMode,
      sendMessage,
      shouldAutoScrollRef,
      state.activeCapability,
      state.isStreaming,
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
  const handleSelectHistoryPicker = useCallback(() => {
    setShowHistoryPicker(true);
  }, []);
  const handleSelectQuestionBankPicker = useCallback(() => {
    setShowQuestionBankPicker(true);
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

  const handleTogglePanelCollapsed = useCallback(() => {
    setPanelCollapsed((prev) => !prev);
  }, []);
  const handleCloseNotebookPicker = useCallback(() => {
    setShowNotebookPicker(false);
  }, []);
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
      <div className="mx-auto flex w-full max-w-[960px] items-center justify-between gap-3 px-4 pt-2 pb-0 sm:px-6 sm:pt-3">
        <span className="min-w-0 truncate text-[15px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
          {t(activeCap.label)}
        </span>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <button
            onClick={() => setShowSaveModal(true)}
            disabled={!chatSavePayload}
            title={t("Save to Notebook")}
            aria-label={t("Save to Notebook")}
            className="inline-flex h-9 w-9 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)]/50 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)] sm:h-auto sm:w-auto sm:px-3 sm:py-1.5"
          >
            <BookOpen className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{t("Save to Notebook")}</span>
          </button>
          <button
            onClick={handleDownloadMarkdown}
            disabled={!state.messages.length}
            title={t("Download chat history as Markdown")}
            aria-label={t("Download Markdown")}
            className="inline-flex h-9 w-9 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)]/50 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--border)]/50 disabled:hover:text-[var(--muted-foreground)] sm:h-auto sm:w-auto sm:px-3 sm:py-1.5"
          >
            <Download className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{t("Download Markdown")}</span>
          </button>
          <button
            onClick={handleNewChat}
            title={t("New chat")}
            aria-label={t("New chat")}
            className="inline-flex h-9 w-9 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)]/50 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] sm:h-auto sm:w-auto sm:px-3 sm:py-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{t("New chat")}</span>
          </button>
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-[960px] flex-1 min-h-0 flex-col overflow-hidden px-4 sm:px-6">
        {!hasMessages ? (
          <div className="flex flex-1 min-h-0 flex-col items-center justify-center animate-fade-in">
            <div className="text-center">
              <h1 className="font-serif text-[28px] font-medium tracking-[-0.01em] text-[var(--foreground)] sm:text-[36px]">
                {t("What would you like to learn?")}
              </h1>
              <p className="mt-3 text-[14px] text-[var(--muted-foreground)] sm:mt-4 sm:text-[15px]">
                {t("Ask anything — I'm here to help you understand.")}
              </p>
            </div>
          </div>
        ) : (
          <div
            ref={messagesContainerRef}
            data-chat-scroll-root="true"
            onScroll={handleMessagesScroll}
            className={`mx-auto w-full flex-1 min-h-0 space-y-6 overflow-y-auto pr-2 [scrollbar-gutter:stable] sm:space-y-7 sm:pr-4 ${hasMessages ? "pt-0" : "pt-2 pb-6"}`}
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
          refMenuRef={refMenuRef}
          refBtnRef={refBtnRef}
          skillMenuRef={skillMenuRef}
          skillBtnRef={skillBtnRef}
          dragCounter={dragCounter}
          dragging={dragging}
          capMenuOpen={capMenuOpen}
          toolMenuOpen={toolMenuOpen}
          refMenuOpen={refMenuOpen}
          skillMenuOpen={skillMenuOpen}
          hasMessages={hasMessages}
          attachments={attachments}
          attachmentError={attachmentError}
          activeCap={activeCap}
          visibleTools={visibleTools}
          selectedTools={selectedTools}
          ragActive={ragActive}
          knowledgeBases={knowledgeBases}
          selectedNotebookRecords={selectedNotebookRecords}
          selectedHistorySessions={selectedHistorySessions}
          selectedQuestionEntries={selectedQuestionEntries}
          notebookReferenceGroups={notebookReferenceGroups}
          availableSkills={availableSkills}
          selectedSkills={selectedSkills}
          skillsAutoMode={skillsAutoMode}
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
          onSetRefMenuOpen={setRefMenuOpen}
          onSetSkillMenuOpen={setSkillMenuOpen}
          onSetKB={handleSetKB}
          onSelectNotebookPicker={handleSelectNotebookPicker}
          onSelectHistoryPicker={handleSelectHistoryPicker}
          onSelectQuestionBankPicker={handleSelectQuestionBankPicker}
          onToggleTool={toggleTool}
          onToggleSkill={handleToggleSkill}
          onSetSkillsAuto={handleSetSkillsAuto}
          onToggleResearchSource={toggleResearchSource}
          onSend={handleSend}
          onRemoveAttachment={removeAttachment}
          onPreviewAttachment={handlePreviewPendingAttachment}
          onRemoveHistory={handleRemoveHistory}
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
