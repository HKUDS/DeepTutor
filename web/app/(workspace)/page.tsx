"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

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
import type { SelectedRecord } from "@/app/(workspace)/guide/types";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import ChatComposer from "@/components/chat/home/ChatComposer";
import { ChatMessageList } from "@/components/chat/home/ChatMessages";
import { apiUrl } from "@/lib/api";
import { useUnifiedChat, type MessageRequestSnapshot } from "@/context/UnifiedChatContext";
import type { StreamEvent } from "@/lib/unified-ws";
import { extractBase64FromDataUrl, readFileAsDataUrl } from "@/lib/file-attachments";
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

const NotebookRecordPicker = dynamic(() => import("@/components/notebook/NotebookRecordPicker"), {
  ssr: false,
});
const HistorySessionPicker = dynamic(() => import("@/components/chat/HistorySessionPicker"), {
  ssr: false,
});
const SaveToNotebookModal = dynamic(() => import("@/components/notebook/SaveToNotebookModal"), {
  ssr: false,
});

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
    allowedTools: ["brainstorm", "rag", "web_search", "code_execution", "reason", "paper_search"],
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
}

function shouldOpenAtPopup(value: string, cursorPos: number): boolean {
  const prefix = value.slice(0, cursorPos);
  return /(^|\s)@[^\s]*$/.test(prefix);
}

function stripTrailingAtMention(value: string): string {
  return value.replace(/(^|\s)@[^\s]*$/, "$1").replace(/\s+$/, "");
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getCapability(value: string | null): CapabilityDef {
  return CAPABILITIES.find((c) => c.value === (value || "")) ?? CAPABILITIES[0];
}

/* ------------------------------------------------------------------ */
/*  Main page                                                         */
/* ------------------------------------------------------------------ */

export default function HomePage() {
  const { t } = useTranslation();
  const {
    state,
    setTools,
    setCapability,
    setKBs,
    sendMessage,
    cancelStreamingTurn,
    newSession,
    loadSession,
  } = useUnifiedChat();
  const [input, setInput] = useState("");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [capabilityConfigs, setCapabilityConfigs] = useState<CapabilityPlaygroundConfigMap>({});
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const [quizConfig, setQuizConfig] = useState<DeepQuestionFormConfig>({ ...DEFAULT_QUIZ_CONFIG });
  const [quizPdf, setQuizPdf] = useState<File | null>(null);
  const [mathAnimatorConfig, setMathAnimatorConfig] = useState<MathAnimatorFormConfig>({
    ...DEFAULT_MATH_ANIMATOR_CONFIG,
  });
  const [visualizeConfig, setVisualizeConfig] = useState<VisualizeFormConfig>({
    ...DEFAULT_VISUALIZE_CONFIG,
  });
  const [researchConfig, setResearchConfig] = useState<DeepResearchFormConfig>(createEmptyResearchConfig());
  const [researchPanelCollapsed, setResearchPanelCollapsed] = useState(true);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showAtPopup, setShowAtPopup] = useState(false);
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [refMenuOpen, setRefMenuOpen] = useState(false);
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<SelectedRecord[]>([]);
  const [selectedHistorySessions, setSelectedHistorySessions] = useState<SelectedHistorySession[]>([]);
  const dragCounter = useRef(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const toolMenuRef = useRef<HTMLDivElement>(null);
  const toolBtnRef = useRef<HTMLButtonElement>(null);
  const refMenuRef = useRef<HTMLDivElement>(null);
  const refBtnRef = useRef<HTMLButtonElement>(null);

  const activeCap = useMemo(() => getCapability(state.activeCapability), [state.activeCapability]);
  const isQuizMode = activeCap.value === "deep_question";
  const isMathAnimatorMode = activeCap.value === "math_animator";
  const isVisualizeMode = activeCap.value === "visualize";
  const isResearchMode = activeCap.value === "deep_research";
  const selectedTools = useMemo(() => new Set(state.enabledTools), [state.enabledTools]);
  const ragActive = isResearchMode ? researchConfig.sources.includes("kb") : selectedTools.has("rag");
  const hasMessages = state.messages.length > 0;
  const activeCapabilityKey = activeCap.value || "chat";
  const { ref: composerRef, height: composerHeight } = useMeasuredHeight<HTMLDivElement>();
  const visibleTools = useMemo(
    () =>
      ALL_TOOLS.filter((t) => activeCap.allowedTools.includes(t.name)),
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
  const chatSavePayload = useMemo(() => {
    if (!state.messages.length) return null;
    const title =
      state.messages.find((msg) => msg.role === "user")?.content.trim().slice(0, 80) ||
      "Chat Session";
    const transcript = state.messages
      .map((msg) => {
        const role =
          msg.role === "user"
            ? "User"
            : msg.role === "assistant"
              ? "Assistant"
              : "System";
        return `## ${role}\n${msg.content}`;
      })
      .join("\n\n");
    return {
      recordType: "chat" as const,
      title,
      userQuery: state.messages
        .filter((msg) => msg.role === "user")
        .map((msg) => msg.content)
        .join("\n\n"),
      output: transcript,
      metadata: {
        source: "chat",
        capability: state.activeCapability || "chat",
        message_count: state.messages.length,
        ui_language: state.language,
        session_id: state.sessionId,
      },
    };
  }, [state.activeCapability, state.language, state.messages, state.sessionId]);
  const activeAssistantMessage = state.isStreaming ? state.messages[state.messages.length - 1] : null;
  const activeUserIndex = useMemo(() => {
    if (!state.isStreaming) return -1;
    for (let index = state.messages.length - 2; index >= 0; index -= 1) {
      if (state.messages[index]?.role === "user") return index;
    }
    return -1;
  }, [state.isStreaming, state.messages]);
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
  const replaySnapshot = useCallback(
    (
      snapshot?: MessageRequestSnapshot,
      configOverride?: Record<string, unknown>,
    ) => {
      if (!snapshot || state.isStreaming) return;
      sendMessage(
        snapshot.content,
        snapshot.attachments,
        configOverride ?? snapshot.config,
        snapshot.notebookReferences,
        snapshot.historyReferences,
        {
          displayUserMessage: false,
          persistUserMessage: false,
          requestSnapshotOverride: snapshot,
        },
      );
      shouldAutoScrollRef.current = true;
    },
    [sendMessage, shouldAutoScrollRef, state.isStreaming],
  );
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
      window.setTimeout(() => {
        sendMessage(
          snapshot.content,
          snapshot.attachments,
          {
            ...(snapshot.config || {}),
            answer_now_context: {
              original_user_message: snapshot.content,
              partial_response: assistantMsg?.content || "",
              events: answerNowEvents,
            },
          },
          snapshot.notebookReferences,
          snapshot.historyReferences,
          {
            displayUserMessage: false,
            persistUserMessage: false,
            requestSnapshotOverride: snapshot,
          },
        );
        shouldAutoScrollRef.current = true;
      }, 0);
    },
    [cancelStreamingTurn, sendMessage, shouldAutoScrollRef, state.isStreaming],
  );

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
      } catch { setKnowledgeBases([]); }
    })();
  }, [setKBs, state.knowledgeBases.length]);

  useEffect(() => {
    setCapabilityConfigs(loadCapabilityPlaygroundConfigs());
  }, []);

  /* URL params */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const p = new URLSearchParams(window.location.search);
    const qc = p.get("capability");
    const qt = p.getAll("tool");
    const session = p.get("session");
    if (qc !== null) handleSelectCapability(qc || "");
    else if (qt.length) {
      const valid = qt.filter((t): t is ToolName => ALL_TOOLS.some((d) => d.name === t));
      if (valid.length) setTools(Array.from(new Set(valid)));
    }
    if (session) {
      void loadSession(session).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        capMenuRef.current && !capMenuRef.current.contains(t) &&
        capBtnRef.current && !capBtnRef.current.contains(t)
      ) {
        setCapMenuOpen(false);
      }
      if (
        toolMenuRef.current && !toolMenuRef.current.contains(t) &&
        toolBtnRef.current && !toolBtnRef.current.contains(t)
      ) {
        setToolMenuOpen(false);
      }
      if (
        refMenuRef.current && !refMenuRef.current.contains(t) &&
        refBtnRef.current && !refBtnRef.current.contains(t)
      ) {
        setRefMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const allowed = new Set(visibleTools.map((tool) => tool.name));
    const nextTools = state.enabledTools.filter((tool) => allowed.has(tool as ToolName));
    if (nextTools.length !== state.enabledTools.length) {
      setTools(nextTools);
    }
  }, [setTools, state.enabledTools, visibleTools]);

  /* Focus textarea */
  useEffect(() => {
    if (!hasMessages) textareaRef.current?.focus();
  }, [hasMessages]);

  /* Smooth auto-resize textarea */
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "28px";
    const next = Math.max(el.scrollHeight, 28);
    const bounded = Math.min(next, 200);
    el.style.height = `${bounded}px`;
    el.style.overflowY = next > 200 ? "auto" : "hidden";
  }, [input, activeCapabilityKey]);

  /* ---- handlers ---- */

  const handleSelectCapability = useCallback(
    (value: string) => {
      const cap = CAPABILITIES.find((c) => c.value === value) ?? CAPABILITIES[0];
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
      if (config.enabledTools.includes("rag") && config.knowledgeBase) {
        setKBs([config.knowledgeBase]);
      }
      setResearchPanelCollapsed(cap.value !== "deep_research");
      setCapMenuOpen(false);
    },
    [capabilityConfigs, setCapability, setKBs, setTools],
  );

  const toggleTool = (tool: string) => {
    if (!activeCap.allowedTools.includes(tool as ToolName)) return;
    if (selectedTools.has(tool)) {
      setTools(state.enabledTools.filter((t) => t !== tool));
    } else {
      setTools([...state.enabledTools, tool]);
    }
  };

  const toggleResearchSource = (source: ResearchSource) => {
    setResearchConfig((current) => ({
      ...current,
      sources: current.sources.includes(source)
        ? current.sources.filter((item) => item !== source)
        : [...current.sources, source],
    }));
  };

  const fileToAttachment = (f: File): Promise<PendingAttachment> =>
    new Promise((resolve, reject) => {
      readFileAsDataUrl(f)
        .then((raw) => {
          const isImage = f.type.startsWith("image/");
          const b64 = extractBase64FromDataUrl(raw);
          resolve({
            type: isImage ? "image" : "file",
            filename: f.name,
            base64: b64,
            previewUrl: isImage ? raw : undefined,
          });
        })
        .catch(reject);
    });

  const handlePaste = async (event: React.ClipboardEvent) => {
    const items = Array.from(event.clipboardData.items);
    const imageFiles = items
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((f): f is File => f !== null);

    if (!imageFiles.length) return;
    event.preventDefault();

    const next = await Promise.all(imageFiles.map(fileToAttachment));
    setAttachments((prev) => [...prev, ...next]);
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.types.includes("Files")) {
      setDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) {
      setDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    dragCounter.current = 0;

    const files = Array.from(e.dataTransfer.files).filter(
      (f) => f.type.startsWith("image/"),
    );
    if (!files.length) return;

    const next = await Promise.all(files.map(fileToAttachment));
    setAttachments((prev) => [...prev, ...next]);
  };

  const handleSend = async () => {
    const content = input.trim();
    if (
      (!content &&
        !attachments.length &&
        !selectedNotebookRecords.length &&
        !selectedHistorySessions.length) ||
      state.isStreaming
    ) {
      return;
    }

    let extraAttachments = attachments.map((a) => ({
      type: a.type,
      filename: a.filename,
      base64: a.base64,
    }));
    let config: Record<string, unknown> | undefined;

    if (isQuizMode) {
      config = buildQuizWSConfig(quizConfig);

      if (quizConfig.mode === "mimic" && quizPdf) {
        const b64 = extractBase64FromDataUrl(await readFileAsDataUrl(quizPdf));
        extraAttachments = [
          ...extraAttachments,
          { type: "pdf", filename: quizPdf.name, base64: b64 },
        ];
      }
    }
    if (isMathAnimatorMode) {
      config = buildMathAnimatorWSConfig(mathAnimatorConfig);
    }
    if (isVisualizeMode) {
      config = buildVisualizeWSConfig(visualizeConfig);
    }
    if (isResearchMode) {
      config = buildResearchWSConfig(researchConfig);
    }

    sendMessage(
      content ||
        (selectedNotebookRecords.length || selectedHistorySessions.length
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
    );
    shouldAutoScrollRef.current = true;
    if (isResearchMode) {
      setResearchPanelCollapsed(true);
    }
    setInput("");
    setAttachments([]);
    setSelectedNotebookRecords([]);
    setSelectedHistorySessions([]);
    setShowAtPopup(false);
  };

  const handleConfirmOutline = useCallback(
    (outline: OutlineItem[], _topic: string, originalConfig?: Record<string, unknown> | null) => {
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
    [researchConfig, sendMessage],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--background)]">
      <div className="mx-auto flex w-full max-w-[960px] flex-1 min-h-0 flex-col overflow-hidden px-6">

        {/* ===== Welcome / Messages ===== */}
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
            className={`mx-auto w-full flex-1 min-h-0 space-y-7 overflow-y-auto pt-6 pr-4 [scrollbar-gutter:stable] ${
              hasMessages ? "" : "pb-6"
            }`}
            style={hasMessages ? { paddingBottom: `${Math.max(composerHeight + 24, 120)}px` } : undefined}
          >
            <div className="flex items-center justify-between pb-2">
              <span className="text-[13px] font-medium text-[var(--muted-foreground)]">{t(activeCap.label)}</span>
              <div className="flex items-center gap-2">
                {chatSavePayload && (
                  <button
                    onClick={() => setShowSaveModal(true)}
                    className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                  >
                    {t("Save to Notebook")}
                  </button>
                )}
                <button
                  onClick={newSession}
                  className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                >
                  {t("New chat")}
                </button>
              </div>
            </div>

            <ChatMessageList
              messages={state.messages}
              isStreaming={state.isStreaming}
              activeUserIndex={activeUserIndex}
              activeAssistantMessage={activeAssistantMessage?.role === "assistant" ? activeAssistantMessage : null}
              sessionId={state.sessionId}
              language={state.language}
              onCancelStreaming={cancelStreamingTurn}
              onAnswerNow={handleAnswerNow}
              onCopyAssistantMessage={copyAssistantMessage}
              onRetryMessage={(snapshot) => replaySnapshot(snapshot)}
              onConfirmOutline={handleConfirmOutline}
            />
            <div ref={messagesEndRef} className="h-px w-full shrink-0" />
          </div>
        )}

        {/* ===== Composer ===== */}
        <ChatComposer
          composerRef={composerRef}
          textareaRef={textareaRef}
          capMenuRef={capMenuRef}
          capBtnRef={capBtnRef}
          toolMenuRef={toolMenuRef}
          toolBtnRef={toolBtnRef}
          refMenuRef={refMenuRef}
          refBtnRef={refBtnRef}
          dragCounter={dragCounter}
          dragging={dragging}
          capMenuOpen={capMenuOpen}
          toolMenuOpen={toolMenuOpen}
          refMenuOpen={refMenuOpen}
          showAtPopup={showAtPopup}
          hasMessages={hasMessages}
          input={input}
          attachments={attachments}
          activeCap={activeCap}
          visibleTools={visibleTools}
          selectedTools={selectedTools}
          ragActive={ragActive}
          knowledgeBases={knowledgeBases}
          selectedNotebookRecords={selectedNotebookRecords}
          selectedHistorySessions={selectedHistorySessions}
          notebookReferenceGroups={notebookReferenceGroups}
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
          researchPanelCollapsed={researchPanelCollapsed}
          capabilities={CAPABILITIES}
          researchSources={RESEARCH_SOURCES}
          onSetCapMenuOpen={setCapMenuOpen}
          onSetToolMenuOpen={setToolMenuOpen}
          onSetRefMenuOpen={setRefMenuOpen}
          onSetShowAtPopup={setShowAtPopup}
          onInputChange={(nextValue, cursorPos) => {
            setInput(nextValue);
            setShowAtPopup(shouldOpenAtPopup(nextValue, cursorPos));
          }}
          onSetKB={(kb) => setKBs(kb ? [kb] : [])}
          onSelectNotebookPicker={() => setShowNotebookPicker(true)}
          onSelectHistoryPicker={() => setShowHistoryPicker(true)}
          onToggleTool={toggleTool}
          onToggleResearchSource={toggleResearchSource}
          onSend={handleSend}
          onRemoveAttachment={removeAttachment}
          onRemoveHistory={(sessionId) =>
            setSelectedHistorySessions((prev) =>
              prev.filter((item) => item.sessionId !== sessionId),
            )
          }
          onRemoveNotebook={(notebookId) =>
            setSelectedNotebookRecords((prev) =>
              prev.filter((record) => record.notebookId !== notebookId),
            )
          }
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onPaste={handlePaste}
          onTextareaClick={(event) => {
            const target = event.currentTarget;
            setShowAtPopup(
              shouldOpenAtPopup(target.value, target.selectionStart ?? target.value.length),
            );
          }}
          onTextareaKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void handleSend();
            } else if (event.key === "Escape") {
              setShowAtPopup(false);
            }
          }}
          onSelectCapability={handleSelectCapability}
          onChangeQuizConfig={setQuizConfig}
          onUploadQuizPdf={setQuizPdf}
          onChangeMathAnimatorConfig={setMathAnimatorConfig}
          onChangeVisualizeConfig={setVisualizeConfig}
          onChangeResearchConfig={setResearchConfig}
          onToggleResearchCollapsed={() => setResearchPanelCollapsed((prev) => !prev)}
        />
      </div>
      <NotebookRecordPicker
        open={showNotebookPicker}
        onClose={() => setShowNotebookPicker(false)}
        onApply={(records) => {
          setInput((prev) => stripTrailingAtMention(prev));
          setSelectedNotebookRecords(records);
        }}
      />
      <HistorySessionPicker
        open={showHistoryPicker}
        onClose={() => setShowHistoryPicker(false)}
        onApply={(sessions) => {
          setInput((prev) => stripTrailingAtMention(prev));
          setSelectedHistorySessions(sessions);
        }}
      />
      <SaveToNotebookModal
        open={showSaveModal}
        payload={chatSavePayload}
        onClose={() => setShowSaveModal(false)}
      />
    </div>
  );
}
