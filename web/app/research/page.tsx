"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Settings,
  Sparkles,
  Play,
  MessageSquare,
  Send,
  Loader2,
  Database,
  GraduationCap,
  Globe,
  FileText,
  Book,
  Download,
  FileDown,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import "katex/dist/katex.min.css";
import { Mermaid } from "@/components/Mermaid";
import { useGlobal } from "@/context/GlobalContext";
import { apiUrl, wsUrl } from "@/lib/api";
import AddToNotebookModal from "@/components/AddToNotebookModal";
import { exportToPdf, preprocessMarkdownForPdf } from "@/lib/pdfExport";
import { useResearchReducer } from "@/hooks/useResearchReducer";
import { ResearchDashboard } from "@/components/research/ResearchDashboard";
import { ResearchEvent } from "@/types/research";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  type?: "topic_proposal";
  proposal?: string;
  original_topic?: string;
  iteration?: number;
  isOptimizing?: boolean;
}

export default function ResearchPage() {
  const {
    researchState: globalResearchState,
    setResearchState: setGlobalResearchState,
  } = useGlobal();

  // Local Reducer State for Deep Research Dashboard
  const [state, dispatch] = useResearchReducer();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Config State
  const [selectedKb, setSelectedKb] = useState<string>("");
  const [kbs, setKbs] = useState<string[]>([]);
  const [planMode, setPlanMode] = useState<string>("medium");
  const [enabledTools, setEnabledTools] = useState<string[]>(["RAG"]);
  const [enableOptimization, setEnableOptimization] = useState<boolean>(true);

  // Chat State
  const [chatHistory, setChatHistory] = useState<ChatMsg[]>([]);
  const [inputTopic, setInputTopic] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Notebook modal state
  const [showNotebookModal, setShowNotebookModal] = useState(false);

  // PDF export state
  const [isExportingPdf, setIsExportingPdf] = useState(false);
  // Ref for report content (hidden rendered report for PDF)
  const reportContentRef = useRef<HTMLDivElement>(null);

  // WebSocket Ref
  const wsRef = useRef<WebSocket | null>(null);

  // Initialize Knowledge Bases
  useEffect(() => {
    fetch(apiUrl("/api/v1/knowledge/list"))
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          const names = data.map((kb: any) => kb.name);
          setKbs(names);
          if (!selectedKb) {
            const defaultKb =
              data.find((kb: any) => kb.is_default)?.name || names[0];
            if (defaultKb) setSelectedKb(defaultKb);
          }
        }
      })
      .catch((err) => console.error("Failed to fetch KBs:", err));
  }, []);

  // Auto-scroll Chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [chatHistory]);

  // Initial Greeting
  useEffect(() => {
    if (chatHistory.length === 0) {
      setChatHistory([
        {
          id: "welcome",
          role: "assistant",
          content:
            "Welcome to Deep Research Lab. \n\nPlease configure your settings above, then enter a research topic below.",
        },
      ]);
    }
  }, []);

  // Select latest active task automatically if none selected
  useEffect(() => {
    if (!selectedTaskId && state.activeTaskIds.length > 0) {
      setSelectedTaskId(state.activeTaskIds[0]);
    }
  }, [state.activeTaskIds, selectedTaskId]);

  // Start Research Function (Local)
  const startResearchLocal = (topic: string) => {
    if (wsRef.current) wsRef.current.close();

    // Update Global State to "running" for sidebar status
    setGlobalResearchState((prev) => ({ ...prev, status: "running", topic }));

    const ws = new WebSocket(wsUrl("/api/v1/research/run"));
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          topic,
          kb_name: selectedKb,
          plan_mode: planMode,
          enabled_tools: enabledTools,
          skip_rephrase: !enableOptimization, // If we already optimized, skip internal rephrase
        }),
      );
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Dispatch all events to reducer
        if (data.type === "progress") {
          // Flatten progress event to match ResearchEvent
          const { type, ...rest } = data;
          // Map stage/status to event type if specific type is generic
          let eventType = data.status as string;
          // Map known statuses to specific event types if needed or pass through
          dispatch({
            type: eventType as any, // dynamic mapping
            ...rest,
          });
        } else if (data.type === "log") {
          dispatch({
            type: "log",
            content: data.content.content || data.content, // Handle different log formats
          });
        } else if (data.type === "result") {
          dispatch({
            type: "reporting_completed",
            word_count: data.metadata?.report_word_count || 0,
            sections: Object.keys(data.metadata?.statistics || {}).length, // approximate
            citations: data.metadata?.statistics?.total_tool_calls || 0,
            report: data.report,
          });
          // Update Global State to "completed"
          setGlobalResearchState((prev) => ({
            ...prev,
            status: "completed",
            report: data.report,
          }));
        } else if (data.type === "error") {
          dispatch({ type: "error", content: data.content });
          setGlobalResearchState((prev) => ({ ...prev, status: "idle" }));
        } else {
          // Forward other events directly
          dispatch(data as ResearchEvent);
        }
      } catch (e) {
        console.error("WS Parse Error", e);
      }
    };

    ws.onerror = (e) => {
      console.error("WS Error", e);
      dispatch({ type: "error", content: "WebSocket connection failed" });
      setGlobalResearchState((prev) => ({ ...prev, status: "idle" }));
    };

    ws.onclose = () => {
      // Optional: handle close
    };
  };

  const handleSendMessage = async () => {
    if (!inputTopic.trim()) return;
    if (state.global.stage !== "idle" && state.global.stage !== "completed")
      return;

    const userMsg: ChatMsg = {
      id: Date.now().toString(),
      role: "user",
      content: inputTopic,
    };

    setChatHistory((prev) => [...prev, userMsg]);
    setInputTopic("");

    if (!enableOptimization) {
      startResearchLocal(userMsg.content);
      return;
    }

    setIsOptimizing(true);
    setChatHistory((prev) => [
      ...prev,
      {
        id: "optimizing",
        role: "assistant",
        content: "Optimizing topic...",
        isOptimizing: true,
      },
    ]);

    try {
      const res = await fetch(apiUrl("/api/v1/research/optimize_topic"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: userMsg.content,
          iteration: 0,
          kb_name: selectedKb,
        }),
      });
      const data = await res.json();

      setChatHistory((prev) => prev.filter((msg) => msg.id !== "optimizing"));

      if (data.error) {
        setChatHistory((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: `Error optimizing: ${data.error}`,
          },
        ]);
      } else {
        const optimizedTopic = data.topic || userMsg.content;
        setChatHistory((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: `I have optimized your topic:\n\n**${optimizedTopic}**\n\n${data.reasoning || ""}\n\nStart research?`,
            type: "topic_proposal",
            proposal: optimizedTopic,
            original_topic: userMsg.content,
          },
        ]);
      }
    } catch (error) {
      setChatHistory((prev) => prev.filter((msg) => msg.id !== "optimizing"));
      setChatHistory((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content: `Network error. Try again.`,
        },
      ]);
    } finally {
      setIsOptimizing(false);
    }
  };

  // PDF Export using the new pdfExport utility
  const handleExportPdf = async () => {
    if (!state.reporting.generatedReport) return;
    if (!reportContentRef.current) return;

    setIsExportingPdf(true);
    try {
      // Wait for Mermaid diagrams and KaTeX formulas to render
      await new Promise((resolve) => setTimeout(resolve, 2000));

      // Use the new PDF export utility
      await exportToPdf(reportContentRef.current, {
        filename: state.planning.originalTopic || "research-report",
        marginLeft: 20,
        marginRight: 20,
        marginTop: 25,
        marginBottom: 25,
        showPageNumbers: true,
        scale: 2,
      });
    } catch (err) {
      console.error("PDF Export failed", err);
    } finally {
      setIsExportingPdf(false);
    }
  };

  return (
    <div className="h-[calc(100vh-4rem)] animate-fade-in flex gap-6">
      {/* LEFT PANEL */}
      <div className="flex-[1_1_33%] min-w-[350px] max-w-[500px] flex flex-col gap-4 h-full">
        {/* Config Header */}
        <div className="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
              <Settings className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              Configuration
            </h2>
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <div
                className={`w-2 h-2 rounded-full ${state.global.stage !== "idle" && state.global.stage !== "completed" ? "bg-emerald-500 animate-pulse" : "bg-slate-300 dark:bg-slate-600"}`}
              />
              {state.global.stage === "idle"
                ? "Idle"
                : state.global.stage === "completed"
                  ? "Completed"
                  : "Running"}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3">
            {/* KB Selection */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                Knowledge Base
              </label>
              <select
                value={selectedKb}
                onChange={(e) => setSelectedKb(e.target.value)}
                className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
              >
                {kbs.length === 0 && <option value="">Loading...</option>}
                {kbs.map((kb) => (
                  <option key={kb} value={kb}>
                    {kb}
                  </option>
                ))}
              </select>
            </div>

            {/* Plan Mode */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                Plan Mode
              </label>
              <div className="flex bg-slate-50 dark:bg-slate-700 p-1 rounded-lg border border-slate-200 dark:border-slate-600">
                {["quick", "medium", "deep", "auto"].map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setPlanMode(mode)}
                    className={`flex-1 py-1.5 text-xs font-medium rounded-md capitalize transition-all ${
                      planMode === mode
                        ? "bg-white dark:bg-slate-600 text-emerald-700 dark:text-emerald-400 shadow-sm border border-slate-100 dark:border-slate-500"
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>

            {/* Tools */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                Research Tools
              </label>
              <div className="flex gap-2">
                {[
                  { key: "RAG", label: "RAG", icon: Database },
                  { key: "Paper", label: "Paper", icon: GraduationCap },
                  { key: "Web", label: "Web", icon: Globe },
                ].map((tool) => {
                  const isSelected = enabledTools.includes(tool.key);
                  const Icon = tool.icon;
                  return (
                    <button
                      key={tool.key}
                      onClick={() => {
                        if (isSelected && enabledTools.length === 1) return;
                        setEnabledTools((prev) =>
                          isSelected
                            ? prev.filter((t) => t !== tool.key)
                            : [...prev, tool.key],
                        );
                      }}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-700"
                          : "bg-slate-50 dark:bg-slate-700 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-600"
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {tool.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Optimization Toggle */}
            <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-700 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600">
              <div className="flex items-center gap-2">
                <Sparkles
                  className={`w-4 h-4 ${enableOptimization ? "text-indigo-500 dark:text-indigo-400" : "text-slate-400 dark:text-slate-500"}`}
                />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  Topic Optimization
                </span>
              </div>
              <button
                onClick={() => setEnableOptimization(!enableOptimization)}
                className={`w-10 h-5 rounded-full relative transition-colors ${enableOptimization ? "bg-indigo-500" : "bg-slate-300 dark:bg-slate-600"}`}
              >
                <div
                  className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform ${enableOptimization ? "left-6" : "left-1"}`}
                />
              </button>
            </div>
          </div>
        </div>

        {/* Chat Interface */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-2">
            <MessageSquare className="w-4 h-4" />
            Topic Assistant
          </div>
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/30 dark:bg-slate-800/30"
          >
            {chatHistory.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm ${msg.role === "user" ? "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-900 dark:text-indigo-100 rounded-tr-none" : "bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded-tl-none shadow-sm"}`}
                >
                  {msg.isOptimizing ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-500 dark:text-indigo-400" />
                      <span>Optimizing topic...</span>
                    </div>
                  ) : (
                    <ReactMarkdown className="prose prose-sm dark:prose-invert max-w-none">
                      {msg.content}
                    </ReactMarkdown>
                  )}
                </div>
                {msg.type === "topic_proposal" &&
                  msg.proposal &&
                  state.global.stage === "idle" && (
                    <div className="mt-2 flex gap-2 animate-fade-in">
                      <button
                        onClick={() => startResearchLocal(msg.proposal!)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white text-xs font-bold rounded-full hover:bg-emerald-700 shadow-lg shadow-emerald-500/20"
                      >
                        <Play className="w-3 h-3" /> Start Research
                      </button>
                    </div>
                  )}
              </div>
            ))}
          </div>
          <div className="p-3 bg-white dark:bg-slate-800 border-t border-slate-100 dark:border-slate-700">
            <div className="relative flex items-center gap-2">
              <input
                type="text"
                value={inputTopic}
                onChange={(e) => setInputTopic(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && !e.shiftKey && handleSendMessage()
                }
                placeholder={
                  state.global.stage !== "idle" &&
                  state.global.stage !== "completed"
                    ? "Research in progress..."
                    : "Enter research topic..."
                }
                disabled={
                  state.global.stage !== "idle" &&
                  state.global.stage !== "completed"
                }
                className="flex-1 pl-4 pr-10 py-2.5 bg-slate-100 dark:bg-slate-700 border-transparent focus:bg-white dark:focus:bg-slate-600 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 rounded-xl text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 transition-all outline-none disabled:opacity-50"
              />
              <button
                onClick={handleSendMessage}
                disabled={
                  !inputTopic.trim() ||
                  (state.global.stage !== "idle" &&
                    state.global.stage !== "completed")
                }
                className="p-2.5 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-50"
              >
                {isOptimizing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* RIGHT PANEL: Research Dashboard */}
      <div className="flex-[2_1_67%] min-w-0 flex flex-col h-full overflow-hidden bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 relative">
        <ResearchDashboard
          state={state}
          selectedTaskId={selectedTaskId}
          onTaskSelect={setSelectedTaskId}
          onAddToNotebook={() => setShowNotebookModal(true)}
          onExportMarkdown={() => {
            const blob = new Blob([state.reporting.generatedReport || ""], {
              type: "text/markdown",
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${state.planning.originalTopic || "report"}.md`;
            a.click();
          }}
          onExportPdf={handleExportPdf}
          isExportingPdf={isExportingPdf}
        />
        {/* Hidden Render Div for PDF - uses preprocessed markdown */}
        <div
          style={{
            position: "absolute",
            top: "-9999px",
            left: "-9999px",
            width: "800px",
          }}
        >
          <div
            ref={reportContentRef}
            className="bg-white"
            style={{
              padding: "50px 40px", // More vertical padding for better page spacing
              fontFamily: "ui-sans-serif, system-ui, sans-serif",
              fontSize: "14px",
              lineHeight: "1.7",
              color: "#1e293b",
            }}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex, rehypeRaw]}
              components={{
                h1: ({ node, ...props }) => (
                  <h1
                    style={{
                      fontSize: "26px",
                      fontWeight: "bold",
                      marginBottom: "20px",
                      paddingBottom: "10px",
                      borderBottom: "2px solid #e2e8f0",
                    }}
                    {...props}
                  />
                ),
                h2: ({ node, ...props }) => (
                  <h2
                    style={{
                      fontSize: "20px",
                      fontWeight: "bold",
                      marginTop: "28px",
                      marginBottom: "14px",
                      color: "#312e81",
                    }}
                    {...props}
                  />
                ),
                h3: ({ node, ...props }) => (
                  <h3
                    style={{
                      fontSize: "16px",
                      fontWeight: "600",
                      marginTop: "20px",
                      marginBottom: "10px",
                    }}
                    {...props}
                  />
                ),
                p: ({ node, ...props }) => (
                  <p
                    style={{ marginBottom: "14px", textAlign: "justify" }}
                    {...props}
                  />
                ),
                table: ({ node, ...props }) => (
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      margin: "18px 0",
                      fontSize: "13px",
                    }}
                    {...props}
                  />
                ),
                th: ({ node, ...props }) => (
                  <th
                    style={{
                      border: "1px solid #cbd5e1",
                      padding: "10px",
                      backgroundColor: "#f1f5f9",
                      fontWeight: "600",
                      textAlign: "left",
                    }}
                    {...props}
                  />
                ),
                td: ({ node, ...props }) => (
                  <td
                    style={{ border: "1px solid #e2e8f0", padding: "10px" }}
                    {...props}
                  />
                ),
                a: ({ node, href, ...props }) => (
                  <a
                    href={href}
                    style={{ color: "#4f46e5", textDecoration: "underline" }}
                    {...props}
                  />
                ),
                blockquote: ({ node, ...props }) => (
                  <blockquote
                    style={{
                      borderLeft: "4px solid #c7d2fe",
                      paddingLeft: "16px",
                      margin: "18px 0",
                      color: "#475569",
                      fontStyle: "italic",
                    }}
                    {...props}
                  />
                ),
                ul: ({ node, ...props }) => (
                  <ul
                    style={{ marginLeft: "24px", marginBottom: "14px" }}
                    {...props}
                  />
                ),
                ol: ({ node, ...props }) => (
                  <ol
                    style={{ marginLeft: "24px", marginBottom: "14px" }}
                    {...props}
                  />
                ),
                li: ({ node, ...props }) => (
                  <li style={{ marginBottom: "6px" }} {...props} />
                ),
                // Handle details/summary for PDF - render as expanded
                details: ({ node, children, ...props }) => (
                  <div
                    style={{
                      marginTop: "8px",
                      marginBottom: "8px",
                      paddingLeft: "12px",
                      borderLeft: "2px solid #e2e8f0",
                    }}
                  >
                    {children}
                  </div>
                ),
                summary: ({ node, children, ...props }) => (
                  <div
                    style={{
                      fontWeight: "600",
                      color: "#475569",
                      marginBottom: "8px",
                    }}
                  >
                    {children}
                  </div>
                ),
                code: ({ node, className, children, ...props }) => {
                  const match = /language-(\w+)/.exec(className || "");
                  const language = match ? match[1] : "";
                  const isInline = !match;

                  // Handle Mermaid diagrams
                  if (language === "mermaid") {
                    const chartCode = String(children).replace(/\n$/, "");
                    return <Mermaid chart={chartCode} />;
                  }

                  return isInline ? (
                    <code
                      style={{
                        backgroundColor: "#f1f5f9",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        fontSize: "13px",
                        fontFamily: "monospace",
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  ) : (
                    <code
                      style={{
                        display: "block",
                        backgroundColor: "#1e293b",
                        color: "#e2e8f0",
                        padding: "16px",
                        borderRadius: "8px",
                        fontSize: "13px",
                        fontFamily: "monospace",
                        overflowX: "auto",
                        whiteSpace: "pre",
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
                pre: ({ node, children, ...props }) => {
                  const child = React.Children.toArray(
                    children,
                  )[0] as React.ReactElement<{ className?: string }>;
                  if (child?.props?.className?.includes("language-mermaid")) {
                    return <>{children}</>;
                  }
                  return (
                    <pre style={{ margin: "18px 0" }} {...props}>
                      {children}
                    </pre>
                  );
                },
              }}
            >
              {preprocessMarkdownForPdf(state.reporting.generatedReport || "")}
            </ReactMarkdown>
          </div>
        </div>
      </div>

      <AddToNotebookModal
        isOpen={showNotebookModal}
        onClose={() => setShowNotebookModal(false)}
        recordType="research"
        title={state.planning.originalTopic || "Research Report"}
        userQuery={state.planning.originalTopic || ""}
        output={state.reporting.generatedReport || ""}
        metadata={{ plan_mode: planMode, enabled_tools: enabledTools }}
        kbName={selectedKb}
      />
    </div>
  );
}
