"use client";

import { Suspense, useState, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  BookOpen,
  MessageSquare,
  Send,
  Loader2,
  ChevronRight,
  ChevronDown,
  Bug,
  CheckCircle2,
  GraduationCap,
  Sparkles,
  ArrowRight,
  Play,
  ChevronLeft,
  X,
  Check,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";

interface Notebook {
  id: string;
  name: string;
  description: string;
  record_count: number;
  color: string;
}

interface NotebookRecord {
  id: string;
  title: string;
  user_query: string;
  output: string;
  type: string;
}

interface SelectedRecord extends NotebookRecord {
  notebookId: string;
  notebookName: string;
}

interface KnowledgePoint {
  knowledge_title: string;
  knowledge_summary: string;
  user_difficulty: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: number;
}

interface SessionState {
  session_id: string | null;
  notebook_id: string | null;
  notebook_name: string;
  knowledge_points: KnowledgePoint[];
  current_index: number;
  current_html: string;
  status: "idle" | "initialized" | "learning" | "completed";
  progress: number;
  summary: string;
}

function GuidePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const entryNotebookId = (searchParams.get("notebook_id") || "").trim();
  const entryNotebookName = (searchParams.get("notebook_name") || "").trim();

  // Multi-notebook selection (same as ideagen)
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
    new Set(),
  );
  const [notebookRecordsMap, setNotebookRecordsMap] = useState<
    Map<string, NotebookRecord[]>
  >(new Map());
  const [selectedRecords, setSelectedRecords] = useState<
    Map<string, SelectedRecord>
  >(new Map()); // recordId -> record with notebook info
  const [loadingNotebooks, setLoadingNotebooks] = useState(true);
  const [loadingRecordsFor, setLoadingRecordsFor] = useState<Set<string>>(
    new Set(),
  );

  // Session state
  const [sessionState, setSessionState] = useState<SessionState>({
    session_id: null,
    notebook_id: null,
    notebook_name: "",
    knowledge_points: [],
    current_index: -1,
    current_html: "",
    status: "idle",
    progress: 0,
    summary: "",
  });

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);

  // UI state
  const [showDebugModal, setShowDebugModal] = useState(false);
  const [debugDescription, setDebugDescription] = useState("");
  const [fixingHtml, setFixingHtml] = useState(false);

  // Sidebar state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWide, setSidebarWide] = useState(false); // false: 1:3, true: 3:1
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");

  const chatContainerRef = useRef<HTMLDivElement>(null);
  const htmlFrameRef = useRef<HTMLIFrameElement>(null);
  const autoSelectionAppliedRef = useRef(false);

  // Load notebooks
  useEffect(() => {
    fetchNotebooks();
  }, []);

  // Auto-scroll chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [chatMessages]);

  // Helper function to inject KaTeX into HTML if needed
  const injectKaTeX = (html: string): string => {
    // Check if KaTeX is already included (case-insensitive)
    const htmlLower = html.toLowerCase();
    const hasKaTeX =
      htmlLower.includes("katex.min.css") ||
      htmlLower.includes("katex.min.js") ||
      htmlLower.includes("katex@") ||
      htmlLower.includes("cdn.jsdelivr.net/npm/katex") ||
      htmlLower.includes("unpkg.com/katex");

    if (hasKaTeX) {
      console.log("KaTeX already included in HTML, skipping injection");
      return html;
    }

    // KaTeX CDN links (using version 0.16.9 for compatibility)
    const katexCSS =
      '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV" crossorigin="anonymous">';
    const katexJS =
      '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" integrity="sha384-XjKyOOlGwcjNTAIQHIpgOno0Hl1YQqzUOEleOLALmuqehneUG+vnGctmUb0ZY0l8" crossorigin="anonymous"></script>';
    const katexAutoRender =
      '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" integrity="sha384-+VBxd3r6XgURycqtZ117n7w6ODWgRrA7TlVzRsFtwW3ZxUo8h4w20Z5J3d3xjfcw" crossorigin="anonymous" onload="renderMathInElement(document.body);"></script>';

    const katexInjection = `  ${katexCSS}\n  ${katexJS}\n  ${katexAutoRender}`;

    // Try to inject into </head> section (most common case)
    if (html.includes("</head>")) {
      console.log("Injecting KaTeX before </head> tag");
      return html.replace("</head>", `${katexInjection}\n</head>`);
    }

    // If no </head> tag, try to inject after <head> tag
    if (html.includes("<head>")) {
      console.log("Injecting KaTeX after <head> tag");
      // Use regex to handle <head> with attributes
      return html.replace(/<head([^>]*)>/i, `<head$1>\n${katexInjection}`);
    }

    // If HTML structure exists but no <head>, add it
    if (html.includes("<html")) {
      console.log("Adding <head> section with KaTeX");
      return html.replace(
        /(<html[^>]*>)/i,
        `$1\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n${katexInjection}\n</head>`,
      );
    }

    // If no HTML structure, wrap it with full HTML document
    console.log("Wrapping content with full HTML document including KaTeX");
    return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
${katexInjection}
</head>
<body>
${html}
</body>
</html>`;
  };

  // Update HTML iframe
  useEffect(() => {
    if (!sessionState.current_html) {
      return;
    }

    // Use setTimeout to ensure DOM is updated
    const timer = setTimeout(() => {
      if (htmlFrameRef.current) {
        const iframe = htmlFrameRef.current;
        console.log(
          "Updating iframe with HTML, length:",
          sessionState.current_html.length,
        );

        // Inject KaTeX support if needed
        const htmlWithKaTeX = injectKaTeX(sessionState.current_html);

        // Use srcdoc attribute (most reliable method)
        try {
          iframe.srcdoc = htmlWithKaTeX;
          console.log("Iframe srcdoc set successfully with KaTeX support");
        } catch (e) {
          console.warn("srcdoc not supported, using contentDocument:", e);
          // Fallback to contentDocument if srcdoc not supported
          const handleLoad = () => {
            try {
              const doc =
                iframe.contentDocument || iframe.contentWindow?.document;
              if (doc) {
                doc.open();
                doc.write(htmlWithKaTeX);
                doc.close();
                console.log(
                  "Iframe content written via contentDocument with KaTeX support",
                );
              }
            } catch (err) {
              console.error("Failed to write to iframe:", err);
            }
          };

          if (
            iframe.contentDocument &&
            iframe.contentDocument.readyState === "complete"
          ) {
            handleLoad();
          } else {
            iframe.onload = handleLoad;
          }
        }
      } else {
        console.warn("htmlFrameRef.current is null");
      }
    }, 100);

    return () => clearTimeout(timer);
  }, [sessionState.current_html, sessionState.current_index]);

  const addLoadingMessage = (message: string) => {
    const loadingMsg: ChatMessage = {
      id: `loading-${Date.now()}`,
      role: "system",
      content: `⏳ ${message}`,
      timestamp: Date.now(),
    };
    setChatMessages((prev) => [...prev, loadingMsg]);
    return loadingMsg.id;
  };

  const removeLoadingMessage = (id: string) => {
    setChatMessages((prev) => prev.filter((msg) => msg.id !== id));
  };

  const fetchNotebooks = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/notebook/list"));
      const data = await res.json();
      const notebooksWithRecords = (data.notebooks || []).filter(
        (nb: Notebook) => nb.record_count > 0,
      );
      setNotebooks(notebooksWithRecords);
      setLoadingNotebooks(false);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
      setLoadingNotebooks(false);
    }
  };

  const fetchNotebookRecords = async (notebookId: string) => {
    const cached = notebookRecordsMap.get(notebookId);
    if (cached) return cached;

    setLoadingRecordsFor((prev) => {
      const newSet = new Set(prev);
      newSet.add(notebookId);
      return newSet;
    });
    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`));
      const data = await res.json();
      const records = data.records || [];
      setNotebookRecordsMap((prev) => new Map(prev).set(notebookId, records));
      return records as NotebookRecord[];
    } catch (err) {
      console.error("Failed to fetch notebook records:", err);
      return [];
    } finally {
      setLoadingRecordsFor((prev) => {
        const newSet = new Set(prev);
        newSet.delete(notebookId);
        return newSet;
      });
    }
  };

  useEffect(() => {
    if (
      autoSelectionAppliedRef.current ||
      !entryNotebookId ||
      loadingNotebooks
    ) {
      return;
    }

    const targetNotebook = notebooks.find((nb) => nb.id === entryNotebookId);
    autoSelectionAppliedRef.current = true;
    if (!targetNotebook) return;

    setExpandedNotebooks((prev) => {
      const next = new Set(prev);
      next.add(targetNotebook.id);
      return next;
    });

    const preselectNotebookRecords = async () => {
      const records = await fetchNotebookRecords(targetNotebook.id);
      if (records.length === 0) return;
      const notebookName = entryNotebookName || targetNotebook.name;
      setSelectedRecords((prev) => {
        const next = new Map(prev);
        records.forEach((record) =>
          next.set(record.id, {
            ...record,
            notebookId: targetNotebook.id,
            notebookName,
          }),
        );
        return next;
      });
    };

    void preselectNotebookRecords();
  }, [
    entryNotebookId,
    entryNotebookName,
    loadingNotebooks,
    notebooks,
    notebookRecordsMap,
  ]);

  const toggleNotebookExpanded = (notebookId: string) => {
    const notebook = notebooks.find((nb) => nb.id === notebookId);
    if (!notebook) return;

    setExpandedNotebooks((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(notebookId)) {
        newSet.delete(notebookId);
      } else {
        newSet.add(notebookId);
        // Fetch records when expanding
        fetchNotebookRecords(notebookId);
      }
      return newSet;
    });
  };

  const toggleRecordSelection = (
    record: NotebookRecord,
    notebookId: string,
    notebookName: string,
  ) => {
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      if (newMap.has(record.id)) {
        newMap.delete(record.id);
      } else {
        newMap.set(record.id, { ...record, notebookId, notebookName });
      }
      return newMap;
    });
  };

  const selectAllFromNotebook = (notebookId: string, notebookName: string) => {
    const records = notebookRecordsMap.get(notebookId) || [];
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      records.forEach((r) =>
        newMap.set(r.id, { ...r, notebookId, notebookName }),
      );
      return newMap;
    });
  };

  const deselectAllFromNotebook = (notebookId: string) => {
    const records = notebookRecordsMap.get(notebookId) || [];
    const recordIds = new Set(records.map((r) => r.id));
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      recordIds.forEach((id) => newMap.delete(id));
      return newMap;
    });
  };

  const clearAllSelections = () => {
    setSelectedRecords(new Map());
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "solve":
        return "bg-blue-100 text-blue-700 border-blue-200";
      case "question":
        return "bg-purple-100 text-purple-700 border-purple-200";
      case "research":
        return "bg-emerald-100 text-emerald-700 border-emerald-200";
      case "co_writer":
        return "bg-amber-100 text-amber-700 border-amber-200";
      default:
        return "bg-slate-100 text-slate-700 border-slate-200";
    }
  };

  const handleCreateSession = async () => {
    if (selectedRecords.size === 0) return;

    setIsLoading(true);
    setLoadingMessage("Analyzing notes and generating learning plan...");
    const loadingId = addLoadingMessage(
      "Analyzing notes and generating learning plan...",
    );

    try {
      // Send records directly for cross-notebook support
      const recordsArray = Array.from(selectedRecords.values()).map((r) => ({
        id: r.id,
        title: r.title,
        user_query: r.user_query,
        output: r.output,
        type: r.type,
      }));

      const res = await fetch(apiUrl("/api/v1/guide/create_session"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records: recordsArray }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");

      if (data.success) {
        // Get notebook names from selected records
        const notebookNames = Array.from(
          new Set(
            Array.from(selectedRecords.values()).map((r) => r.notebookName),
          ),
        );
        const notebookName =
          notebookNames.length === 1
            ? notebookNames[0]
            : `跨笔记本（${notebookNames.length} 个笔记本，${selectedRecords.size} 条记录）`;

        setSessionState({
          session_id: data.session_id,
          notebook_id: "cross_notebook",
          notebook_name: notebookName,
          knowledge_points: data.knowledge_points || [],
          current_index: -1,
          current_html: "",
          status: "initialized",
          progress: 0,
          summary: "",
        });

        // Add system message: show learning plan
        const planMessage = `📚 Learning plan generated with **${data.total_points}** knowledge points:\n\n${data.knowledge_points.map((kp: KnowledgePoint, idx: number) => `${idx + 1}. ${kp.knowledge_title}`).join("\n")}\n\nClick "Start Learning" button above to begin!`;
        setChatMessages([
          {
            id: "plan",
            role: "system",
            content: planMessage,
            timestamp: Date.now(),
          },
        ]);
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "system",
            content: `❌ Failed to create session: ${data.error}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");
      console.error("Failed to create session:", err);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "system",
          content: "❌ Failed to create session, please try again later",
          timestamp: Date.now(),
        },
      ]);
    }
  };

  const handleStartLearning = async () => {
    if (!sessionState.session_id) return;

    setIsLoading(true);
    setLoadingMessage("Generating interactive learning page...");
    const loadingId = addLoadingMessage(
      "Generating interactive learning page...",
    );

    try {
      const res = await fetch(apiUrl("/api/v1/guide/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionState.session_id }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");

      if (data.success) {
        // Ensure HTML exists
        const htmlContent = data.html || "";
        console.log("Start learning - HTML length:", htmlContent.length);

        setSessionState((prev) => ({
          ...prev,
          current_index: data.current_index,
          current_html: htmlContent,
          status: "learning",
          progress: data.progress || 0,
        }));

        // Add system message
        setChatMessages((prev) => [
          ...prev,
          {
            id: `start-${Date.now()}`,
            role: "system",
            content: data.message || "Starting the first knowledge point",
            timestamp: Date.now(),
          },
        ]);
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "system",
            content: `❌ Failed to start learning: ${data.error || "Unknown error"}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");
      console.error("Failed to start learning:", err);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "system",
          content: "❌ Failed to start learning, please try again later",
          timestamp: Date.now(),
        },
      ]);
    }
  };

  const handleNextKnowledge = async () => {
    if (!sessionState.session_id) return;

    setIsLoading(true);
    setLoadingMessage("正在生成下一个知识点...");
    const loadingId = addLoadingMessage("正在生成下一个知识点...");

    try {
      const res = await fetch(apiUrl("/api/v1/guide/next"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionState.session_id }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");

      if (data.success) {
        if (data.status === "completed") {
          // Learning completed
          setSessionState((prev) => ({
            ...prev,
            status: "completed",
            summary: data.summary || "",
            progress: 100,
          }));

          setChatMessages((prev) => [
            ...prev,
            {
              id: `complete-${Date.now()}`,
              role: "system",
              content: data.message || "🎉 恭喜你完成了全部知识点！",
              timestamp: Date.now(),
            },
          ]);
        } else {
          // Move to next knowledge point
          setSessionState((prev) => ({
            ...prev,
            current_index: data.current_index,
            current_html: data.html || "",
            progress: data.progress || 0,
          }));

          setChatMessages((prev) => [
            ...prev,
            {
              id: `next-${Date.now()}`,
              role: "system",
              content: data.message || "Moving to next knowledge point",
              timestamp: Date.now(),
            },
          ]);
        }
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "system",
            content: `❌ Failed to move to next: ${data.error || "Unknown error"}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      setIsLoading(false);
      setLoadingMessage("");
      console.error("Failed to move to next:", err);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "system",
          content: "❌ Failed to move to next, please try again later",
          timestamp: Date.now(),
        },
      ]);
    }
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !sessionState.session_id || sendingMessage)
      return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: inputMessage,
      timestamp: Date.now(),
    };

    setChatMessages((prev) => [...prev, userMsg]);
    const userInput = inputMessage;
    setInputMessage("");
    setSendingMessage(true);

    // Add thinking indicator
    const thinkingId = addLoadingMessage("Thinking...");

    try {
      const res = await fetch(apiUrl("/api/v1/guide/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionState.session_id,
          message: userInput,
        }),
      });
      const data = await res.json();

      removeLoadingMessage(thinkingId);

      if (data.success) {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: data.answer || "",
            timestamp: Date.now(),
          },
        ]);
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "assistant",
            content: `❌ Error: ${data.error || "Failed to respond"}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err) {
      removeLoadingMessage(thinkingId);
      console.error("Failed to send message:", err);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "❌ Failed to send message, please try again later",
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setSendingMessage(false);
    }
  };

  const handleFixHtml = async () => {
    if (!sessionState.session_id || !debugDescription.trim() || fixingHtml)
      return;

    setFixingHtml(true);
    const loadingId = addLoadingMessage("正在修复 HTML 页面...");

    try {
      const res = await fetch(apiUrl("/api/v1/guide/fix_html"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionState.session_id,
          bug_description: debugDescription,
        }),
      });
      const data = await res.json();

      removeLoadingMessage(loadingId);

      if (data.success) {
        setSessionState((prev) => ({
          ...prev,
          current_html: data.html || prev.current_html,
        }));
        setShowDebugModal(false);
        setDebugDescription("");
        setChatMessages((prev) => [
          ...prev,
          {
            id: `fix-${Date.now()}`,
            role: "system",
            content: "✅ HTML page has been fixed!",
            timestamp: Date.now(),
          },
        ]);
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "system",
            content: `❌ 修复失败：${data.error || "未知错误"}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err) {
      removeLoadingMessage(loadingId);
      console.error("Failed to fix HTML:", err);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "system",
          content: "❌ 修复失败，请稍后重试",
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setFixingHtml(false);
    }
  };

  const canStart =
    sessionState.status === "initialized" &&
    sessionState.knowledge_points.length > 0;
  const canNext =
    sessionState.status === "learning" &&
    sessionState.current_index < sessionState.knowledge_points.length - 1;
  const isCompleted = sessionState.status === "completed";
  const isLastKnowledge =
    sessionState.status === "learning" &&
    sessionState.current_index === sessionState.knowledge_points.length - 1;

  // Calculate widths based on ratio
  const leftWidthPercent = sidebarCollapsed ? 0 : sidebarWide ? 75 : 25; // 3:1 or 1:3
  const rightWidthPercent = sidebarCollapsed ? 100 : sidebarWide ? 25 : 75;
  const hasEntryNotebook = entryNotebookId.length > 0;
  const handleBackToNotebook = () => {
    if (!hasEntryNotebook) return;
    router.push(`/notebooks/${encodeURIComponent(entryNotebookId)}`);
  };

  return (
    <div className="h-screen flex gap-0 p-4 animate-fade-in relative">
      {/* LEFT PANEL: Chat & Control */}
      <div
        className={`flex flex-col gap-4 h-full transition-all duration-300 flex-shrink-0 mr-4 ${sidebarCollapsed ? "overflow-hidden" : ""}`}
        style={{
          width: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
          minWidth: sidebarCollapsed
            ? 0
            : `${Math.max(leftWidthPercent * 0.01 * 1200, 300)}px`,
          maxWidth: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
        }}
      >
        {/* Multi-Notebook Selection (same as ideagen) */}
        {sessionState.status === "idle" && (
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
            <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
              <h2 className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                选择来源（跨笔记本）
              </h2>
              {selectedRecords.size > 0 && (
                <button
                  onClick={clearAllSelections}
                  className="text-xs text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400"
                >
                  清空（{selectedRecords.size}）
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto max-h-[400px]">
              {loadingNotebooks ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-indigo-600 dark:text-indigo-400" />
                </div>
              ) : notebooks.length === 0 ? (
                <div className="p-4 text-center text-sm text-slate-400 dark:text-slate-500">
                  未找到包含记录的笔记本
                </div>
              ) : (
                <div className="divide-y divide-slate-100 dark:divide-slate-700">
                  {notebooks.map((notebook) => {
                    const isExpanded = expandedNotebooks.has(notebook.id);
                    const records = notebookRecordsMap.get(notebook.id) || [];
                    const isLoading = loadingRecordsFor.has(notebook.id);
                    const selectedFromThis = records.filter((r) =>
                      selectedRecords.has(r.id),
                    ).length;

                    return (
                      <div key={notebook.id}>
                        {/* Notebook Header */}
                        <div
                          className="p-3 flex items-center gap-2 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                          onClick={() => toggleNotebookExpanded(notebook.id)}
                        >
                          {isExpanded ? (
                            <ChevronDown className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                          )}
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{
                              backgroundColor: notebook.color || "#94a3b8",
                            }}
                          />
                          <span className="flex-1 text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                            {notebook.name}
                          </span>
                          <span className="text-xs text-slate-400 dark:text-slate-500">
                            {selectedFromThis > 0 && (
                              <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                                {selectedFromThis}/
                              </span>
                            )}
                            {notebook.record_count}
                          </span>
                        </div>

                        {/* Records List */}
                        {isExpanded && (
                          <div className="pl-6 pr-2 pb-2 bg-slate-50/50 dark:bg-slate-800/50">
                            {isLoading ? (
                              <div className="flex items-center justify-center py-4">
                                <Loader2 className="w-4 h-4 animate-spin text-indigo-600 dark:text-indigo-400" />
                              </div>
                            ) : records.length === 0 ? (
                              <div className="py-2 text-xs text-slate-400 dark:text-slate-500 text-center">
                                暂无记录
                              </div>
                            ) : (
                              <>
                                <div className="flex gap-2 mb-2">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      selectAllFromNotebook(
                                        notebook.id,
                                        notebook.name,
                                      );
                                    }}
                                    className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
                                  >
                                    Select All
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      deselectAllFromNotebook(notebook.id);
                                    }}
                                    className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                                  >
                                    Deselect
                                  </button>
                                </div>
                                <div className="space-y-1">
                                  {records.map((record) => (
                                    <div
                                      key={record.id}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        toggleRecordSelection(
                                          record,
                                          notebook.id,
                                          notebook.name,
                                        );
                                      }}
                                      className={`p-2 rounded-lg cursor-pointer transition-all border ${
                                        selectedRecords.has(record.id)
                                          ? "bg-indigo-50 dark:bg-indigo-900/30 border-indigo-200 dark:border-indigo-700"
                                          : "hover:bg-white dark:hover:bg-slate-700 border-transparent hover:border-slate-200 dark:hover:border-slate-600"
                                      }`}
                                    >
                                      <div className="flex items-center gap-2">
                                        <div
                                          className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                                            selectedRecords.has(record.id)
                                              ? "bg-indigo-500 border-indigo-500 text-white"
                                              : "border-slate-300 dark:border-slate-500"
                                          }`}
                                        >
                                          {selectedRecords.has(record.id) && (
                                            <Check className="w-2.5 h-2.5" />
                                          )}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                          <span
                                            className={`text-[10px] font-bold uppercase px-1 py-0.5 rounded ${getTypeColor(record.type)}`}
                                          >
                                            {record.type}
                                          </span>
                                          <span className="text-xs text-slate-700 dark:text-slate-200 ml-2 truncate">
                                            {record.title}
                                          </span>
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Generate Button */}
            <div className="p-3 border-t border-slate-100 dark:border-slate-700">
              <button
                onClick={handleCreateSession}
                disabled={isLoading || selectedRecords.size === 0}
                className="w-full px-4 py-2.5 bg-gradient-to-r from-indigo-500 to-purple-500 text-white rounded-xl hover:from-indigo-600 hover:to-purple-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 font-medium shadow-md shadow-indigo-500/20"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate Learning Plan ({selectedRecords.size} items)
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Progress Bar with Action Buttons */}
        {sessionState.status !== "idle" && (
          <div className="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                Learning Progress
              </span>
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {sessionState.progress}%
              </span>
            </div>
            <div className="h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden mb-4">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                style={{ width: `${sessionState.progress}%` }}
              />
            </div>
            {sessionState.knowledge_points.length > 0 && (
              <p className="text-xs text-slate-400 dark:text-slate-500 mb-4">
                Knowledge Point {sessionState.current_index + 1} /{" "}
                {sessionState.knowledge_points.length}
              </p>
            )}

            {/* Action Buttons */}
            <div className="flex gap-2">
              {canStart && (
                <button
                  onClick={handleStartLearning}
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm font-medium"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4" />
                      Start Learning
                    </>
                  )}
                </button>
              )}

              {canNext && (
                <button
                  onClick={handleNextKnowledge}
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm font-medium"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      加载中...
                    </>
                  ) : (
                    <>
                      <ChevronRight className="w-4 h-4" />
                      下一步
                    </>
                  )}
                </button>
              )}

              {isLastKnowledge && (
                <button
                  onClick={handleNextKnowledge}
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm font-medium"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      正在生成总结...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      完成学习
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        )}

        {/* Chat Interface */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-2">
            <MessageSquare className="w-4 h-4" />
            学习助手
          </div>

          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/30 dark:bg-slate-800/30"
          >
            {chatMessages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm ${
                    msg.role === "user"
                      ? "bg-indigo-600 text-white rounded-tr-none shadow-md shadow-indigo-500/20"
                      : msg.role === "system" && msg.content.includes("⏳")
                        ? "bg-amber-50 border border-amber-200 text-amber-900 rounded-tl-none"
                        : msg.role === "system"
                          ? "bg-blue-50 border border-blue-200 text-blue-900 rounded-tl-none"
                          : "bg-white border border-slate-200 text-slate-700 rounded-tl-none shadow-sm"
                  }`}
                >
                  {msg.role === "system" ? (
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                        components={{
                          table: ({ ...props }) => (
                            <div className="overflow-x-auto my-4 rounded-lg border border-slate-200 shadow-sm">
                              <table
                                className="min-w-full divide-y divide-slate-200 text-sm"
                                {...props}
                              />
                            </div>
                          ),
                          thead: ({ ...props }) => (
                            <thead className="bg-slate-50" {...props} />
                          ),
                          th: ({ ...props }) => (
                            <th
                              className="px-3 py-2 text-left font-semibold text-slate-700 whitespace-nowrap border-b border-slate-200"
                              {...props}
                            />
                          ),
                          tbody: ({ ...props }) => (
                            <tbody
                              className="divide-y divide-slate-100 bg-white"
                              {...props}
                            />
                          ),
                          td: ({ ...props }) => (
                            <td
                              className="px-3 py-2 text-slate-600 border-b border-slate-100"
                              {...props}
                            />
                          ),
                          tr: ({ ...props }) => (
                            <tr
                              className="hover:bg-slate-50/50 transition-colors"
                              {...props}
                            />
                          ),
                        }}
                      >
                        {processLatexContent(msg.content)}
                      </ReactMarkdown>
                    </div>
                  ) : msg.role === "assistant" ? (
                    <div className="prose prose-sm max-w-none prose-slate">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                        components={{
                          table: ({ ...props }) => (
                            <div className="overflow-x-auto my-4 rounded-lg border border-slate-200 shadow-sm">
                              <table
                                className="min-w-full divide-y divide-slate-200 text-sm"
                                {...props}
                              />
                            </div>
                          ),
                          thead: ({ ...props }) => (
                            <thead className="bg-slate-50" {...props} />
                          ),
                          th: ({ ...props }) => (
                            <th
                              className="px-3 py-2 text-left font-semibold text-slate-700 whitespace-nowrap border-b border-slate-200"
                              {...props}
                            />
                          ),
                          tbody: ({ ...props }) => (
                            <tbody
                              className="divide-y divide-slate-100 bg-white"
                              {...props}
                            />
                          ),
                          td: ({ ...props }) => (
                            <td
                              className="px-3 py-2 text-slate-600 border-b border-slate-100"
                              {...props}
                            />
                          ),
                          tr: ({ ...props }) => (
                            <tr
                              className="hover:bg-slate-50/50 transition-colors"
                              {...props}
                            />
                          ),
                        }}
                      >
                        {processLatexContent(msg.content)}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <p>{msg.content}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Input Area */}
          {sessionState.status === "learning" && (
            <div className="p-3 bg-white dark:bg-slate-800 border-t border-slate-100 dark:border-slate-700">
              <div className="relative flex items-center gap-2">
                <input
                  type="text"
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) =>
                    e.key === "Enter" && !e.shiftKey && handleSendMessage()
                  }
                  placeholder="有问题吗？随时可以提问..."
                  disabled={sendingMessage}
                  className="flex-1 pl-4 pr-10 py-2.5 bg-slate-100 dark:bg-slate-700 border-transparent focus:bg-white dark:focus:bg-slate-600 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 rounded-xl text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 transition-all outline-none disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!inputMessage.trim() || sendingMessage}
                  className="p-2.5 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-indigo-500/20"
                >
                  {sendingMessage ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT PANEL: Interactive Content */}
      <div
        className="flex flex-col h-full overflow-hidden transition-all duration-300 flex-1 relative"
        style={{ width: `${rightWidthPercent}%` }}
      >
        {/* Collapse/Expand and Width Toggle Button - positioned relative to right panel */}
        <div className="absolute top-4 left-4 z-20 flex gap-2">
          {hasEntryNotebook && (
            <button
              onClick={handleBackToNotebook}
              className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all text-slate-500 dark:text-slate-300"
              title={
                entryNotebookName
                  ? `返回笔记本：${entryNotebookName}`
                  : "返回来源笔记本"
              }
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all"
            title={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            ) : (
              <ChevronLeft className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            )}
          </button>
          {!sidebarCollapsed && (
            <button
              onClick={() => setSidebarWide(!sidebarWide)}
              className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all"
              title={
                sidebarWide ? "切换为窄侧边栏（1:3）" : "切换为宽侧边栏（3:1）"
              }
            >
              <ArrowRight
                className={`w-4 h-4 text-slate-600 dark:text-slate-300 transition-transform ${sidebarWide ? "rotate-180" : ""}`}
              />
            </button>
          )}
        </div>
        {sessionState.status === "idle" ? (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col items-center justify-center text-slate-300 dark:text-slate-600 p-8">
            <GraduationCap className="w-24 h-24 text-slate-200 dark:text-slate-600 mb-6" />
            <h3 className="text-lg font-medium text-slate-600 dark:text-slate-300 mb-2">
              引导式学习
            </h3>
            <p className="text-sm text-slate-400 dark:text-slate-500 max-w-md text-center leading-relaxed">
              选择一个笔记本，系统将生成个性化学习计划。通过交互页面与智能问答，
              你将逐步掌握全部内容。
            </p>
          </div>
        ) : isCompleted ? (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden relative">
            {/* Summary Header */}
            <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-emerald-50 to-indigo-50 dark:from-emerald-900/20 dark:to-indigo-900/20 flex items-center justify-between shrink-0">
              <h2 className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                学习总结
              </h2>
            </div>
            {/* Summary Content */}
            <div className="flex-1 overflow-y-auto p-8 bg-white dark:bg-slate-800">
              <div className="prose prose-slate dark:prose-invert prose-headings:font-bold prose-h1:text-2xl prose-h2:text-xl max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    table: ({ ...props }) => (
                      <div className="overflow-x-auto my-6 rounded-lg border border-slate-200 shadow-sm">
                        <table
                          className="min-w-full divide-y divide-slate-200 text-sm"
                          {...props}
                        />
                      </div>
                    ),
                    thead: ({ ...props }) => (
                      <thead className="bg-slate-50" {...props} />
                    ),
                    th: ({ ...props }) => (
                      <th
                        className="px-4 py-3 text-left font-semibold text-slate-700 whitespace-nowrap border-b border-slate-200"
                        {...props}
                      />
                    ),
                    tbody: ({ ...props }) => (
                      <tbody
                        className="divide-y divide-slate-100 bg-white"
                        {...props}
                      />
                    ),
                    td: ({ ...props }) => (
                      <td
                        className="px-4 py-3 text-slate-600 border-b border-slate-100"
                        {...props}
                      />
                    ),
                    tr: ({ ...props }) => (
                      <tr
                        className="hover:bg-slate-50/50 transition-colors"
                        {...props}
                      />
                    ),
                  }}
                >
                  {processLatexContent(sessionState.summary || "")}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        ) : sessionState.status === "learning" ? (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden relative">
            {/* Debug Button */}
            <button
              onClick={() => setShowDebugModal(true)}
              className="absolute top-4 right-4 z-10 p-2 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg transition-colors shadow-sm"
              title="修复 HTML"
            >
              <Bug className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            </button>

            {/* HTML Content */}
            {sessionState.current_html ? (
              <iframe
                ref={htmlFrameRef}
                className="w-full h-full border-0"
                title="交互式学习内容"
                sandbox="allow-scripts allow-same-origin"
                key={`html-${sessionState.current_index}-${sessionState.current_html.length}`}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="w-12 h-12 text-indigo-400 dark:text-indigo-500 animate-spin mb-4" />
                <p className="text-slate-500 dark:text-slate-400">
                  {loadingMessage || "正在加载学习内容..."}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col items-center justify-center text-slate-300 dark:text-slate-600 p-8">
            <Loader2 className="w-12 h-12 text-indigo-400 dark:text-indigo-500 animate-spin mb-4" />
            <p className="text-slate-500 dark:text-slate-400">
              {loadingMessage || "正在加载学习内容..."}
            </p>
          </div>
        )}
      </div>

      {/* Debug Modal */}
      {showDebugModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-in fade-in">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-[500px] animate-in zoom-in-95">
            <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
              <h3 className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <Bug className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                修复 HTML 问题
              </h3>
              <button
                onClick={() => {
                  setShowDebugModal(false);
                  setDebugDescription("");
                }}
                className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  问题描述
                </label>
                <textarea
                  value={debugDescription}
                  onChange={(e) => setDebugDescription(e.target.value)}
                  placeholder="描述 HTML 问题，例如：按钮无法点击、样式显示异常、交互不生效..."
                  rows={6}
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 outline-none resize-none"
                />
              </div>
            </div>
            <div className="p-4 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowDebugModal(false);
                  setDebugDescription("");
                }}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleFixHtml}
                disabled={!debugDescription.trim() || fixingHtml}
                className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {fixingHtml ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    修复中...
                  </>
                ) : (
                  <>
                    <Bug className="w-4 h-4" />
                    修复
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function GuidePage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center">
          加载中...
        </div>
      }
    >
      <GuidePageContent />
    </Suspense>
  );
}
