"use client";

import { useState, useEffect, useRef } from "react";
import {
  Send,
  Loader2,
  Terminal,
  Bot,
  User,
  CheckCircle2,
  Book,
  Activity,
  Cpu,
  DollarSign,
  Search,
  Sparkles,
  FileText,
  Trash2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { useGlobal } from "@/context/GlobalContext";
import { API_BASE_URL, apiUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";
import AddToNotebookModal from "@/components/AddToNotebookModal";

const resolveArtifactUrl = (url?: string | null, outputDir?: string) => {
  if (!url) return "";

  // Already absolute http/https URL
  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  const normalized = url.replace(/^\.\//, "");

  // Backend already rewrote to /api/outputs/solve/...
  if (normalized.startsWith("/api/outputs/")) {
    return `${API_BASE_URL}${normalized}`;
  }

  if (normalized.startsWith("api/outputs/")) {
    return `${API_BASE_URL}/${normalized}`;
  }

  if (normalized.startsWith("artifacts/") && outputDir) {
    return `${API_BASE_URL}/api/outputs/solve/${outputDir}/${normalized}`;
  }

  return url;
};

export default function SolverPage() {
  const { solverState, setSolverState, startSolver, newSolverSession } = useGlobal();

  // Local state for input
  const [inputQuestion, setInputQuestion] = useState("");
  const [kbs, setKbs] = useState<string[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const prevLogsLengthRef = useRef<number>(0);
  const prevMessagesLengthRef = useRef<number>(0);
  const prevIsSolvingForLogsRef = useRef<boolean>(false);
  const prevIsSolvingForChatRef = useRef<boolean>(false);

  // Notebook modal state
  const [showNotebookModal, setShowNotebookModal] = useState(false);
  const [notebookRecord, setNotebookRecord] = useState<{
    title: string;
    userQuery: string;
    output: string;
  } | null>(null);

  useEffect(() => {
    // Fetch knowledge bases on mount only
    fetch(apiUrl("/api/v1/knowledge/list"))
      .then((res) => res.json())
      .then((data) => {
        const names = data.map((kb: any) => kb.name);
        setKbs(names);
        if (!solverState.selectedKb) {
          const defaultKb = data.find((kb: any) => kb.is_default)?.name;
          if (defaultKb)
            setSolverState((prev) => ({ ...prev, selectedKb: defaultKb }));
          else if (names.length > 0)
            setSolverState((prev) => ({ ...prev, selectedKb: names[0] }));
        }
      })
      .catch((err) => console.error("Failed to fetch KBs:", err));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll logs (only when solving and new logs are added)
  useEffect(() => {
    const isSolvingChanged =
      prevIsSolvingForLogsRef.current !== solverState.isSolving;

    // Reset counter when starting a new solving session
    if (isSolvingChanged && solverState.isSolving) {
      prevLogsLengthRef.current = 0;
    }

    if (logContainerRef.current && solverState.isSolving) {
      const currentLogsLength = solverState.logs.length;
      // Only scroll if there are new logs (logs length increased) and we have logs
      if (
        currentLogsLength > prevLogsLengthRef.current &&
        currentLogsLength > 0
      ) {
        const container = logContainerRef.current;
        // Use requestAnimationFrame to ensure DOM is updated
        requestAnimationFrame(() => {
          container.scrollTo({
            top: container.scrollHeight,
            behavior: "smooth",
          });
        });
      }
      prevLogsLengthRef.current = currentLogsLength;
    } else if (!solverState.isSolving) {
      // Reset when solving stops
      prevLogsLengthRef.current = solverState.logs.length;
    }

    prevIsSolvingForLogsRef.current = solverState.isSolving;
  }, [solverState.logs, solverState.isSolving]);

  // Auto-scroll chat (only when solving and new messages are added)
  useEffect(() => {
    const isSolvingChanged =
      prevIsSolvingForChatRef.current !== solverState.isSolving;

    // Reset counter when starting a new solving session
    if (isSolvingChanged && solverState.isSolving) {
      prevMessagesLengthRef.current = solverState.messages.length;
    }

    if (chatEndRef.current && solverState.isSolving) {
      const currentMessagesLength = solverState.messages.length;
      // Only scroll if there are new messages (messages length increased)
      // But don't scroll immediately when solving starts (user message was just added)
      if (
        currentMessagesLength > prevMessagesLengthRef.current &&
        !isSolvingChanged
      ) {
        // Use requestAnimationFrame to ensure DOM is updated
        requestAnimationFrame(() => {
          chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
        });
      }
      prevMessagesLengthRef.current = currentMessagesLength;
    } else if (!solverState.isSolving) {
      // Reset when solving stops
      prevMessagesLengthRef.current = solverState.messages.length;
    }

    prevIsSolvingForChatRef.current = solverState.isSolving;
  }, [solverState.messages, solverState.isSolving]);

  const handleStart = () => {
    if (!inputQuestion.trim()) return;
    startSolver(inputQuestion, solverState.selectedKb);
    setInputQuestion("");
  };

  return (
    <div className="h-screen flex gap-0 animate-fade-in overflow-hidden">
      {/* Left Panel: Chat Interface */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-800 border-r border-slate-200 dark:border-slate-700 overflow-hidden min-h-0">
        {/* Chat Header */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200 font-semibold">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            Smart Solver
          </div>
          <div className="flex items-center gap-2">
            <select
              value={solverState.selectedKb}
              onChange={(e) =>
                setSolverState((prev) => ({
                  ...prev,
                  selectedKb: e.target.value,
                }))
              }
              className="text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md px-2 py-1 outline-none focus:border-blue-400 dark:text-slate-200"
            >
              {kbs.map((kb) => (
                <option key={kb} value={kb}>
                  {kb}
                </option>
              ))}
            </select>
            {solverState.messages.length > 0 && (
              <button
                onClick={newSolverSession}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                title="New Session"
              >
                <Trash2 className="w-3.5 h-3.5" />
                New
              </button>
            )}
          </div>
        </div>

        {/* Chat Area */}
        <div
          ref={chatContainerRef}
          className="flex-1 overflow-y-auto p-6 space-y-6 bg-slate-50/30 dark:bg-slate-900/30 min-h-0"
        >
          {/* Initial State */}
          {solverState.messages.length === 0 && !solverState.isSolving && (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto">
              <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 rounded-2xl flex items-center justify-center mb-6 shadow-sm">
                <Bot className="w-8 h-8" />
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-2">
                How can I help you today?
              </h3>
              <p className="text-slate-500 dark:text-slate-400 mb-8 leading-relaxed">
                I can help you solve complex STEM problems using multi-step
                reasoning. Try asking about calculus, physics, or coding
                algorithms.
              </p>
              <div className="grid grid-cols-1 gap-3 w-full text-sm">
                {[
                  "Calculate the linear convolution of x=[1,2,3] and h=[4,5]",
                  "Explain the backpropagation algorithm in neural networks",
                  "Solve the differential equation dy/dx = x^2",
                ].map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setInputQuestion(q)}
                    className="px-4 py-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl hover:border-blue-300 dark:hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 hover:text-blue-700 dark:hover:text-blue-400 transition-all text-left text-slate-600 dark:text-slate-300 shadow-sm"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages List */}
          {solverState.messages.map((msg, idx) => (
            <div
              key={idx}
              className="flex gap-4 w-full animate-in fade-in slide-in-from-bottom-4"
            >
              {msg.role === "user" ? (
                <>
                  <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center shrink-0">
                    <User className="w-5 h-5 text-slate-500 dark:text-slate-400" />
                  </div>
                  <div className="flex-1 bg-slate-100 dark:bg-slate-700 px-5 py-3.5 rounded-2xl rounded-tl-none text-slate-800 dark:text-slate-200 leading-relaxed shadow-sm overflow-hidden min-w-0 break-words">
                    <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:font-bold prose-p:leading-relaxed prose-pre:bg-slate-900 prose-pre:shadow-inner prose-pre:overflow-x-auto prose-code:break-words prose-a:break-all">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                        urlTransform={(url) =>
                          resolveArtifactUrl(url, msg.outputDir)
                        }
                        components={{
                          img: ({ node, src, alt, ...props }) => (
                            // eslint-disable-next-line @next/next/no-img-element -- Dynamic images from markdown content
                            <img
                              {...props}
                              src={
                                resolveArtifactUrl(
                                  typeof src === "string" ? src : "",
                                  msg.outputDir,
                                ) || undefined
                              }
                              alt={alt || "Solution image"}
                              loading="lazy"
                              className="max-w-full h-auto"
                            />
                          ),
                          a: ({ node, href, ...props }) => (
                            <a
                              {...props}
                              href={
                                resolveArtifactUrl(
                                  typeof href === "string" ? href : "",
                                  msg.outputDir,
                                ) || undefined
                              }
                              target="_blank"
                              rel="noreferrer"
                              className="break-all"
                            />
                          ),
                          pre: ({ node, ...props }) => (
                            <pre
                              {...props}
                              className="overflow-x-auto max-w-full"
                            />
                          ),
                          code: ({ node, className, children, ...props }) => {
                            const isInline = !className;
                            return (
                              <code
                                {...props}
                                className={isInline ? "break-words" : "block"}
                              >
                                {children}
                              </code>
                            );
                          },
                          table: ({ node, ...props }) => (
                            <div className="overflow-x-auto">
                              <table {...props} className="min-w-full" />
                            </div>
                          ),
                        }}
                      >
                        {processLatexContent(msg.content)}
                      </ReactMarkdown>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center shrink-0 shadow-lg shadow-blue-500/30">
                    <Bot className="w-5 h-5 text-white" />
                  </div>
                  <div className="flex-1 bg-white dark:bg-slate-800 px-6 py-5 rounded-2xl rounded-tl-none border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden min-w-0 break-words">
                    <div className="prose prose-slate dark:prose-invert prose-blue max-w-none prose-headings:font-bold prose-p:leading-relaxed prose-pre:bg-slate-900 prose-pre:shadow-inner prose-pre:overflow-x-auto prose-code:break-words prose-a:break-all">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                        urlTransform={(url) =>
                          resolveArtifactUrl(url, msg.outputDir)
                        }
                        components={{
                          img: ({ node, src, alt, ...props }) => (
                            // eslint-disable-next-line @next/next/no-img-element -- Dynamic images from markdown content
                            <img
                              {...props}
                              src={
                                resolveArtifactUrl(
                                  typeof src === "string" ? src : "",
                                  msg.outputDir,
                                ) || undefined
                              }
                              alt={alt || "Solution image"}
                              loading="lazy"
                              className="max-w-full h-auto"
                            />
                          ),
                          a: ({ node, href, ...props }) => (
                            <a
                              {...props}
                              href={
                                resolveArtifactUrl(
                                  typeof href === "string" ? href : "",
                                  msg.outputDir,
                                ) || undefined
                              }
                              target="_blank"
                              rel="noreferrer"
                              className="break-all"
                            />
                          ),
                          pre: ({ node, ...props }) => (
                            <pre
                              {...props}
                              className="overflow-x-auto max-w-full"
                            />
                          ),
                          code: ({ node, className, children, ...props }) => {
                            const isInline = !className;
                            return (
                              <code
                                {...props}
                                className={isInline ? "break-words" : "block"}
                              >
                                {children}
                              </code>
                            );
                          },
                          table: ({ node, ...props }) => (
                            <div className="overflow-x-auto">
                              <table {...props} className="min-w-full" />
                            </div>
                          ),
                        }}
                      >
                        {processLatexContent(msg.content)}
                      </ReactMarkdown>
                    </div>
                    <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400 font-medium">
                        <CheckCircle2 className="w-4 h-4" />
                        Verified by DeepTutor Logic Engine
                      </div>
                      <button
                        onClick={() => {
                          // Find corresponding user question
                          const userMsgIndex = solverState.messages.findIndex(
                            (m, i) =>
                              m.role === "user" &&
                              solverState.messages[i + 1]?.role ===
                                "assistant" &&
                              solverState.messages[i + 1]?.content ===
                                msg.content,
                          );
                          const userQuery =
                            userMsgIndex >= 0
                              ? solverState.messages[userMsgIndex].content
                              : solverState.question;
                          setNotebookRecord({
                            title:
                              userQuery.slice(0, 100) +
                              (userQuery.length > 100 ? "..." : ""),
                            userQuery,
                            output: msg.content,
                          });
                          setShowNotebookModal(true);
                        }}
                        className="flex items-center gap-1 px-2 py-1 text-xs text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 rounded-lg transition-colors"
                      >
                        <Book className="w-3 h-3" />
                        Add to Notebook
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}

          {/* AI Thinking State */}
          {solverState.isSolving && (
            <div className="flex gap-4 w-full animate-in fade-in slide-in-from-bottom-2">
              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center shrink-0 shadow-lg shadow-blue-500/30">
                <Loader2 className="w-5 h-5 text-white animate-spin" />
              </div>
              <div className="flex flex-col gap-2 flex-1 min-w-0">
                <div className="bg-white dark:bg-slate-800 px-5 py-4 rounded-2xl rounded-tl-none border border-slate-100 dark:border-slate-700 shadow-sm">
                  {/* Stage Display */}
                  <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200 text-sm mb-3">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                    </span>
                    <span className="font-semibold">
                      {solverState.progress.stage === "investigate" &&
                        "🔍 Investigating..."}
                      {solverState.progress.stage === "solve" &&
                        "🧮 Solving..."}
                      {solverState.progress.stage === "response" &&
                        "✍️ Responding..."}
                      {!solverState.progress.stage &&
                        "Reasoning Engine Active..."}
                    </span>
                  </div>

                  {/* Progress Details */}
                  {solverState.progress.stage === "investigate" &&
                    solverState.progress.progress.queries &&
                    solverState.progress.progress.queries.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs text-slate-600 dark:text-slate-400 font-medium">
                          Round {solverState.progress.progress.round || 1} -
                          Tool Queries:
                        </div>
                        <div className="space-y-1">
                          {solverState.progress.progress.queries.map(
                            (query, idx) => (
                              <div
                                key={idx}
                                className="text-xs text-slate-500 dark:text-slate-400 pl-3 border-l-2 border-blue-200 dark:border-blue-600"
                              >
                                • {query}
                              </div>
                            ),
                          )}
                        </div>
                      </div>
                    )}

                  {solverState.progress.stage === "solve" &&
                    solverState.progress.progress.step_id && (
                      <div className="text-xs text-slate-600 dark:text-slate-400">
                        <span className="font-medium">
                          Solve step{" "}
                          {solverState.progress.progress.step_index || "?"}:
                        </span>{" "}
                        <span className="text-slate-500 dark:text-slate-400">
                          {solverState.progress.progress.step_target || ""}
                        </span>
                      </div>
                    )}

                  {solverState.progress.stage === "response" &&
                    solverState.progress.progress.step_id && (
                      <div className="text-xs text-slate-600 dark:text-slate-400">
                        <span className="font-medium">
                          Responding step{" "}
                          {solverState.progress.progress.step_index || "?"}:
                        </span>{" "}
                        <span className="text-slate-500 dark:text-slate-400">
                          {solverState.progress.progress.step_target || ""}
                        </span>
                      </div>
                    )}

                  {!solverState.progress.stage && (
                    <>
                      <div className="h-2 w-32 bg-slate-100 dark:bg-slate-700 rounded animate-pulse mb-2"></div>
                      <div className="h-2 w-48 bg-slate-100 dark:bg-slate-700 rounded animate-pulse"></div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input Area */}
        <div className="p-4 bg-white dark:bg-slate-800 border-t border-slate-100 dark:border-slate-700 shrink-0">
          <div className="w-full relative">
            <input
              type="text"
              className="w-full px-5 py-4 pr-32 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-slate-400 dark:placeholder:text-slate-500 text-slate-700 dark:text-slate-200 shadow-inner"
              placeholder="Ask a difficult question..."
              value={inputQuestion}
              onChange={(e) => setInputQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleStart()}
              disabled={solverState.isSolving}
            />
            <div className="absolute right-2 top-2 bottom-2 flex items-center gap-2">
              <button
                onClick={handleStart}
                disabled={solverState.isSolving || !inputQuestion.trim()}
                className="h-full aspect-square bg-blue-600 text-white rounded-lg flex items-center justify-center hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 transition-all shadow-md shadow-blue-500/20"
              >
                {solverState.isSolving ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
          <div className="text-center text-[10px] text-slate-400 dark:text-slate-500 mt-2">
            DeepTutor can make mistakes. Please verify important information.
          </div>
        </div>
      </div>

      {/* Right Panel: Logic Stream - Modern Light Theme */}
      <div className="w-[400px] flex-shrink-0 bg-white dark:bg-slate-800 flex flex-col overflow-hidden border-l border-slate-200 dark:border-slate-700 h-full">
        {/* Header */}
        <div className="px-4 py-3 bg-slate-50/50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
            <Activity className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
            Logic Stream
          </div>
          {solverState.isSolving && (
            <span className="flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400 font-medium">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              Running
            </span>
          )}
        </div>

        {/* Performance & Cost - Horizontal Layout */}
        {solverState.tokenStats.calls > 0 && (
          <div className="px-4 py-2.5 bg-slate-50 dark:bg-slate-900/50 border-b border-slate-100 dark:border-slate-700 shrink-0">
            <div className="flex items-center gap-3 flex-wrap text-xs">
              <div className="flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
                <span className="text-slate-500 dark:text-slate-400">
                  Model:
                </span>
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  {solverState.tokenStats.model}
                </span>
              </div>
              <div className="h-3 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="text-slate-500 dark:text-slate-400">
                Calls:{" "}
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  {solverState.tokenStats.calls}
                </span>
              </div>
              <div className="h-3 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="text-slate-500 dark:text-slate-400">
                Tokens:{" "}
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  {solverState.tokenStats.tokens.toLocaleString()}
                </span>
              </div>
              <div className="h-3 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="flex items-center gap-1">
                <DollarSign className="w-3 h-3 text-amber-500" />
                <span className="font-semibold text-amber-600 dark:text-amber-400">
                  ${solverState.tokenStats.cost.toFixed(4)}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Current Progress Display */}
        {solverState.isSolving && solverState.progress.stage && (
          <div className="px-4 py-3 bg-indigo-50 dark:bg-indigo-900/30 border-b border-indigo-100 dark:border-indigo-800 shrink-0">
            <div className="flex items-center gap-2 mb-2">
              <div
                className={`p-1.5 rounded-lg ${
                  solverState.progress.stage === "investigate"
                    ? "bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400"
                    : solverState.progress.stage === "solve"
                      ? "bg-amber-100 dark:bg-amber-900/50 text-amber-600 dark:text-amber-400"
                      : "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400"
                }`}
              >
                {solverState.progress.stage === "investigate" && (
                  <Search className="w-3.5 h-3.5" />
                )}
                {solverState.progress.stage === "solve" && (
                  <Sparkles className="w-3.5 h-3.5" />
                )}
                {solverState.progress.stage === "response" && (
                  <FileText className="w-3.5 h-3.5" />
                )}
              </div>
              <div>
                <div className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 capitalize">
                  {solverState.progress.stage === "investigate" &&
                    "Investigating"}
                  {solverState.progress.stage === "solve" && "Solving"}
                  {solverState.progress.stage === "response" && "Responding"}
                </div>
                {solverState.progress.progress.round && (
                  <div className="text-[10px] text-indigo-500 dark:text-indigo-400">
                    Round {solverState.progress.progress.round}
                  </div>
                )}
              </div>
            </div>

            {/* Investigate stage - show queries */}
            {solverState.progress.stage === "investigate" &&
              solverState.progress.progress.queries &&
              solverState.progress.progress.queries.length > 0 && (
                <div className="space-y-1 mt-2">
                  {solverState.progress.progress.queries
                    .slice(0, 3)
                    .map((query, idx) => (
                      <div
                        key={idx}
                        className="text-[10px] text-indigo-600 dark:text-indigo-400 pl-2 border-l-2 border-indigo-200 dark:border-indigo-600 truncate"
                      >
                        {query}
                      </div>
                    ))}
                  {solverState.progress.progress.queries.length > 3 && (
                    <div className="text-[10px] text-indigo-400 dark:text-indigo-500 pl-2">
                      +{solverState.progress.progress.queries.length - 3} more
                      queries...
                    </div>
                  )}
                </div>
              )}

            {/* Solve/Response stage - show step info */}
            {(solverState.progress.stage === "solve" ||
              solverState.progress.stage === "response") &&
              solverState.progress.progress.step_id && (
                <div className="text-[10px] text-indigo-600 dark:text-indigo-400 mt-1">
                  Step {solverState.progress.progress.step_index || "?"}:{" "}
                  {solverState.progress.progress.step_target || "Processing..."}
                </div>
              )}
          </div>
        )}

        {/* Activity Log */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between shrink-0">
            <h3 className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
              Activity Log
            </h3>
            <span className="text-[10px] text-slate-400 dark:text-slate-500">
              {solverState.logs.length} entries
            </span>
          </div>

          <div
            ref={logContainerRef}
            className="flex-1 overflow-y-auto overflow-x-hidden p-3 space-y-1.5 min-h-0"
          >
            {solverState.logs.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 gap-3 py-12">
                <Activity className="w-10 h-10 opacity-20" />
                <p className="text-sm">Waiting for logic execution...</p>
              </div>
            )}

            {(() => {
              // Filter and deduplicate logs
              const filteredLogs = solverState.logs.filter((log, i) => {
                const content = (log.content || "").trim();

                // Filter empty content
                if (!content) return false;

                // Filter duplicate content (same content appeared in recent 10 logs)
                const recentLogs = solverState.logs.slice(
                  Math.max(0, i - 10),
                  i,
                );
                if (
                  recentLogs.some((l) => (l.content || "").trim() === content)
                ) {
                  return false;
                }

                // Filter some unimportant debug info
                if (
                  content.includes("Provider List:") ||
                  (content.includes("INFO:") &&
                    !content.includes("[Stage:") &&
                    !content.includes("🔧")) ||
                  (content.match(/^\d{4}-\d{2}-\d{2}/) &&
                    !content.includes("[Stage:")) ||
                  (content.includes("INFO:MainSolver:") &&
                    !content.includes("[Stage:")) ||
                  (content.includes("INFO:investigate_agent:") &&
                    !content.includes("🔧") &&
                    !content.includes("[Stage:"))
                ) {
                  return false;
                }

                // Fix incorrect ERROR tags
                if (log.level === "ERROR" && content.includes("INFO:")) {
                  log.level = "INFO";
                }

                return true;
              });

              return filteredLogs.map((log, i) => {
                const content = log.content || "";

                // Clean content: remove duplicate INFO prefix
                let cleanContent = content;
                cleanContent = cleanContent.replace(/^INFO:[^:]+:/, "");
                cleanContent = cleanContent.replace(
                  /^ERROR:[^:]+:INFO:/,
                  "INFO:",
                );

                // Parse stage progress format
                const stageMatch = cleanContent.match(
                  /^([▶…✔↷⚠✖•])\s*\[Stage:([^\]]+)\]\s*(\w+)(?:\s*\|\s*(.+))?/,
                );

                // Parse tool call format
                const toolMatch = cleanContent.match(
                  /🔧\s*\[Tool Call\]\s*Tool:\s*(.+)/,
                );

                // Parse separator line
                const isSeparator = /^={20,}$/.test(cleanContent.trim());

                // Parse errors
                const isError =
                  (log.level === "ERROR" && !cleanContent.includes("INFO:")) ||
                  (cleanContent.includes("ERROR") &&
                    !cleanContent.includes("INFO:")) ||
                  cleanContent.includes("✖");

                // Parse warnings
                const isWarning =
                  log.level === "WARNING" ||
                  cleanContent.includes("WARNING") ||
                  cleanContent.includes("⚠");

                // Parse completion markers
                const isComplete =
                  cleanContent.includes("✔") ||
                  cleanContent.includes("✓") ||
                  cleanContent.includes("complete");

                // Parse running state
                const isRunning =
                  cleanContent.includes("…") || cleanContent.includes("▶");

                // Parse skip state
                const isSkip = cleanContent.includes("↷");

                // Parse step header
                const isStepHeader = /^---\s*Step\s+\d+:\s*S\d+\s*---/.test(
                  cleanContent,
                );

                // Parse section header
                const isSectionHeader =
                  /^\[(Plan|Solve|Response|Analysis|Note|Finalize|PrecisionAnswer)\]\s*/.test(
                    cleanContent,
                  );

                // Parse tool call detail line
                const isToolDetail =
                  cleanContent.includes("🔧 [Tool Call]") ||
                  cleanContent.includes("Tool:") ||
                  cleanContent.includes("Status:") ||
                  cleanContent.includes("Duration:");

                // Parse action lines
                const isActionLine =
                  /^\s*•\s*/.test(cleanContent) ||
                  /^\s*\[(Investigate|Note|Solve|Response)\]\s*/.test(
                    cleanContent,
                  );

                // Light/Dark theme styles
                let className = "text-xs px-2 py-1.5 rounded break-words";
                let prefix = "";

                if (stageMatch) {
                  const [, icon, , status] = stageMatch;
                  prefix = icon;

                  if (status === "start" || status === "running") {
                    className +=
                      " bg-indigo-50 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-l-2 border-indigo-300 dark:border-indigo-500";
                  } else if (status === "complete") {
                    className +=
                      " bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-l-2 border-emerald-300 dark:border-emerald-500";
                  } else if (status === "error") {
                    className +=
                      " bg-red-50 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-l-2 border-red-300 dark:border-red-500";
                  } else if (status === "warning") {
                    className +=
                      " bg-amber-50 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-l-2 border-amber-300 dark:border-amber-500";
                  } else if (status === "skip") {
                    className +=
                      " bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-l-2 border-slate-200 dark:border-slate-600";
                  } else {
                    className +=
                      " bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400";
                  }
                } else if (isSeparator) {
                  className +=
                    " text-slate-300 dark:text-slate-600 text-center";
                } else if (isError) {
                  className +=
                    " bg-red-50 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-l-2 border-red-300 dark:border-red-500";
                } else if (isWarning) {
                  className +=
                    " bg-amber-50 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-l-2 border-amber-300 dark:border-amber-500";
                } else if (isStepHeader) {
                  className +=
                    " bg-blue-50 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-semibold mt-2";
                } else if (isSectionHeader) {
                  className +=
                    " bg-indigo-50 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 font-medium mt-2";
                } else if (toolMatch || isToolDetail) {
                  className +=
                    " bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-l-2 border-emerald-200 dark:border-emerald-500";
                } else if (isActionLine) {
                  className +=
                    " bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 pl-4";
                } else if (isComplete) {
                  className +=
                    " bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300";
                } else if (isRunning) {
                  className +=
                    " bg-indigo-50 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300";
                } else if (isSkip) {
                  className +=
                    " bg-slate-50 dark:bg-slate-800 text-slate-400 dark:text-slate-500";
                } else {
                  className +=
                    " bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700";
                }

                return (
                  <div key={i} className={className}>
                    {prefix && (
                      <span className="mr-1.5 opacity-70">{prefix}</span>
                    )}
                    {cleanContent}
                  </div>
                );
              });
            })()}
          </div>
        </div>
      </div>

      {/* Add to Notebook Modal */}
      {notebookRecord && (
        <AddToNotebookModal
          isOpen={showNotebookModal}
          onClose={() => {
            setShowNotebookModal(false);
            setNotebookRecord(null);
          }}
          recordType="solve"
          title={notebookRecord.title}
          userQuery={notebookRecord.userQuery}
          output={notebookRecord.output}
          kbName={solverState.selectedKb}
        />
      )}
    </div>
  );
}
