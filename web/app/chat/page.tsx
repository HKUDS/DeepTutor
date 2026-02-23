"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  Send,
  Loader2,
  MessageSquare,
  Database,
  Globe,
  Settings,
  Plus,
  Trash2,
  ChevronLeft,
  Book,
  User,
  Bot,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl, wsUrl } from "@/lib/api";
import AddToNotebookModal from "@/components/AddToNotebookModal";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  sources?: {
    rag?: any[];
    web?: any[];
  };
}

interface ChatSession {
  session_id: string;
  title: string;
  created_at: string;
  message_count: number;
}

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
}

function ChatPageContent() {
  const searchParams = useSearchParams();
  const sessionFromUrl = searchParams.get("session");
  const CHAT_SETTINGS_KEY = "deeptutor.chat.settings";
  const CHAT_ACTIVE_SESSION_KEY = "deeptutor.chat.active_session";

  // State
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "👋 你好！我是你的智能助手。我可以帮你查询知识库或搜索网络信息。有什么可以帮你的吗？",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [showSidebar, setShowSidebar] = useState(true);

  // Settings
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState<string>("");
  const [enableRag, setEnableRag] = useState(false);
  const [enableWebSearch, setEnableWebSearch] = useState(false);

  // Notebook modal
  const [showNotebookModal, setShowNotebookModal] = useState(false);
  const [selectedMessageContent, setSelectedMessageContent] = useState("");

  // Refs
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const readChatSettingsStore = () => {
    try {
      const raw = localStorage.getItem(CHAT_SETTINGS_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      return parsed as Record<
        string,
        { enableRag?: boolean; enableWebSearch?: boolean; selectedKb?: string }
      >;
    } catch {
      return {};
    }
  };

  const writeChatSettingsStore = (
    store: Record<
      string,
      { enableRag?: boolean; enableWebSearch?: boolean; selectedKb?: string }
    >,
  ) => {
    try {
      localStorage.setItem(CHAT_SETTINGS_KEY, JSON.stringify(store));
    } catch {
      // Ignore storage failures
    }
  };

  const persistSessionSettings = (
    sid: string,
    settings: {
      enableRag: boolean;
      enableWebSearch: boolean;
      selectedKb: string;
    },
  ) => {
    const store = readChatSettingsStore();
    store[sid] = settings;
    writeChatSettingsStore(store);
  };

  const loadSessionSettings = (
    sid: string,
    fallback?: {
      kb_name?: string;
      enable_rag?: boolean;
      enable_web_search?: boolean;
    },
  ) => {
    const store = readChatSettingsStore();
    if (store[sid]) {
      return {
        enableRag: !!store[sid].enableRag,
        enableWebSearch: !!store[sid].enableWebSearch,
        selectedKb: store[sid].selectedKb || "",
      };
    }
    if (fallback) {
      return {
        enableRag: !!fallback.enable_rag,
        enableWebSearch: !!fallback.enable_web_search,
        selectedKb: fallback.kb_name || "",
      };
    }
    return null;
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/chat/sessions?limit=20"));
      const data = await res.json();
      if (Array.isArray(data)) {
        setSessions(data);
      }
    } catch (err) {
      console.error("Failed to fetch sessions:", err);
    }
  };

  // Fetch knowledge bases
  useEffect(() => {
    fetch(apiUrl("/api/v1/knowledge/list"))
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setKbs(data);
          const defaultKb =
            data.find((kb: KnowledgeBase) => kb.is_default)?.name ||
            data[0]?.name;
          if (defaultKb) {
            setSelectedKb((prev) => prev || defaultKb);
          }
        }
      })
      .catch((err) => console.error("Failed to fetch KBs:", err));
  }, []);

  // Fetch sessions
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchSessions();
  }, []);

  // Auto-load session from URL query parameter (e.g., /chat?session=xxx)
  useEffect(() => {
    if (sessionFromUrl && sessionFromUrl !== sessionId) {
      handleLoadSession(sessionFromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionFromUrl]);

  // Restore last active session if no session in URL
  useEffect(() => {
    if (sessionFromUrl || sessionId) return;
    try {
      const lastSessionId = localStorage.getItem(CHAT_ACTIVE_SESSION_KEY);
      if (lastSessionId) {
        handleLoadSession(lastSessionId);
      }
    } catch {
      // Ignore storage failures
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist tool settings for active session
  useEffect(() => {
    if (!sessionId) return;
    persistSessionSettings(sessionId, {
      enableRag,
      enableWebSearch,
      selectedKb,
    });
    try {
      localStorage.setItem(CHAT_ACTIVE_SESSION_KEY, sessionId);
    } catch {
      // Ignore storage failures
    }
  }, [sessionId, enableRag, enableWebSearch, selectedKb]);

  // Auto-scroll
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages]);

  // Send message
  const handleSend = () => {
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // Create assistant placeholder
    const assistantId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", isStreaming: true },
    ]);

    // Build explicit history from current messages (excluding welcome and the new user message)
    const historyForBackend = messages
      .filter(
        (msg) =>
          msg.id !== "welcome" &&
          (msg.role === "user" || msg.role === "assistant") &&
          !msg.isStreaming &&
          msg.content,
      )
      .map((msg) => ({ role: msg.role, content: msg.content }));

    // Open WebSocket
    const ws = new WebSocket(wsUrl("/api/v1/chat"));
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          message: userMessage.content,
          session_id: sessionId,
          history: historyForBackend,
          kb_name: selectedKb,
          enable_rag: enableRag && !!selectedKb,
          enable_web_search: enableWebSearch,
        }),
      );
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "session") {
          setSessionId(data.session_id);
          persistSessionSettings(data.session_id, {
            enableRag,
            enableWebSearch,
            selectedKb,
          });
          try {
            localStorage.setItem(CHAT_ACTIVE_SESSION_KEY, data.session_id);
          } catch {
            // Ignore storage failures
          }
          fetchSessions(); // Refresh session list
        } else if (data.type === "stream") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, content: msg.content + data.content }
                : msg,
            ),
          );
        } else if (data.type === "result") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, content: data.content, isStreaming: false }
                : msg,
            ),
          );
          setIsLoading(false);
        } else if (data.type === "sources") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? { ...msg, sources: { rag: data.rag, web: data.web } }
                : msg,
            ),
          );
        } else if (data.type === "status") {
          // Update streaming message with status
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId && msg.content === ""
                ? { ...msg, content: `🔍 ${data.message}` }
                : msg,
            ),
          );
        } else if (data.type === "error") {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId
                ? {
                    ...msg,
                    content: `❌ 错误: ${data.message}`,
                    isStreaming: false,
                  }
                : msg,
            ),
          );
          setIsLoading(false);
        }
      } catch (e) {
        console.error("WebSocket parse error:", e);
      }
    };

    ws.onerror = () => {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId
            ? { ...msg, content: "❌ 连接失败，请重试", isStreaming: false }
            : msg,
        ),
      );
      setIsLoading(false);
    };

    ws.onclose = () => {
      setIsLoading(false);
    };
  };

  // Start new chat — fully reset state and close any active connection
  const handleNewChat = () => {
    // Close any active WebSocket to prevent stale responses leaking in
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsLoading(false);
    setSessionId(null);
    setEnableRag(false);
    setEnableWebSearch(false);
    setMessages([
      {
        id: "welcome",
        role: "assistant",
        content: "👋 新对话已开始。有什么可以帮你的吗？",
      },
    ]);
    try {
      localStorage.removeItem(CHAT_ACTIVE_SESSION_KEY);
    } catch {
      // Ignore storage failures
    }
  };

  // Load session — close active connection and replace messages entirely
  const handleLoadSession = async (sid: string) => {
    // Close any active WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsLoading(false);

    try {
      const res = await fetch(apiUrl(`/api/v1/chat/sessions/${sid}`));
      const data = await res.json();
      if (data.messages) {
        setSessionId(sid);
        const settings = loadSessionSettings(sid, data.settings);
        if (settings) {
          setEnableRag(settings.enableRag);
          setEnableWebSearch(settings.enableWebSearch);
          if (settings.selectedKb) {
            setSelectedKb(settings.selectedKb);
          }
        }
        setMessages(
          data.messages.map((msg: any, idx: number) => ({
            id: `${sid}-${idx}`,
            role: msg.role,
            content: msg.content,
            sources: msg.sources,
          })),
        );
      }
    } catch (err) {
      console.error("Failed to load session:", err);
    }
  };

  // Delete session
  const handleDeleteSession = async (sid: string) => {
    try {
      await fetch(apiUrl(`/api/v1/chat/sessions/${sid}`), { method: "DELETE" });
      fetchSessions();
      if (sessionId === sid) {
        handleNewChat();
      }
    } catch (err) {
      console.error("Failed to delete session:", err);
    }
  };

  // Add to notebook
  const handleAddToNotebook = (content: string) => {
    setSelectedMessageContent(content);
    setShowNotebookModal(true);
  };

  return (
    <div className="h-screen flex bg-slate-50">
      {/* Sidebar */}
      {showSidebar && (
        <div className="w-64 bg-white border-r border-slate-200 flex flex-col">
          {/* Header */}
          <div className="p-4 border-b border-slate-200">
            <button
              onClick={handleNewChat}
              className="w-full py-2.5 px-4 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              新对话
            </button>
          </div>

          {/* Sessions */}
          <div className="flex-1 overflow-y-auto p-2">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-2 py-2">
              历史对话
            </div>
            {sessions.length === 0 ? (
              <p className="text-sm text-slate-400 px-2 py-4 text-center">
                暂无历史对话
              </p>
            ) : (
              <div className="space-y-1">
                {sessions.map((session) => (
                  <div
                    key={session.session_id}
                    onClick={() => handleLoadSession(session.session_id)}
                    className={`group p-2 rounded-lg cursor-pointer flex items-center justify-between ${
                      sessionId === session.session_id
                        ? "bg-blue-50 text-blue-700"
                        : "hover:bg-slate-50 text-slate-700"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <MessageSquare className="w-4 h-4 shrink-0" />
                      <span className="text-sm truncate">{session.title}</span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteSession(session.session_id);
                      }}
                      className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-100 rounded text-red-500"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Settings */}
          <div className="p-3 border-t border-slate-200">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              <Settings className="w-3 h-3 inline mr-1" />
              设置
            </div>

            {/* Knowledge Base */}
            <div className="mb-3">
              <label className="text-xs text-slate-500 mb-1 block">
                知识库
              </label>
              <select
                value={selectedKb}
                onChange={(e) => setSelectedKb(e.target.value)}
                className="w-full px-2 py-1.5 bg-slate-50 border border-slate-200 rounded text-sm"
              >
                {kbs.map((kb) => (
                  <option key={kb.name} value={kb.name}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Toggles */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-blue-500" />
                  <span className="text-xs text-slate-600">知识库检索</span>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableRag}
                    onChange={(e) => setEnableRag(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-8 h-4 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Globe className="w-3.5 h-3.5 text-emerald-500" />
                  <span className="text-xs text-slate-600">联网搜索</span>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableWebSearch}
                    onChange={(e) => setEnableWebSearch(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-8 h-4 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-emerald-600"></div>
                </label>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="h-14 bg-white border-b border-slate-200 flex items-center px-4 gap-4">
          {!showSidebar && (
            <button
              onClick={() => setShowSidebar(true)}
              className="p-2 hover:bg-slate-100 rounded-lg"
            >
              <ChevronLeft className="w-5 h-5 rotate-180" />
            </button>
          )}
          {showSidebar && (
            <button
              onClick={() => setShowSidebar(false)}
              className="p-2 hover:bg-slate-100 rounded-lg"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
          )}
          <h1 className="font-semibold text-slate-900">智能对话</h1>
          <div className="ml-auto flex items-center gap-2 text-sm text-slate-500">
            {enableRag && selectedKb && (
              <span className="px-2 py-1 bg-blue-50 text-blue-600 rounded-full text-xs flex items-center gap-1">
                <Database className="w-3 h-3" />
                {selectedKb}
              </span>
            )}
            {enableWebSearch && (
              <span className="px-2 py-1 bg-emerald-50 text-emerald-600 rounded-full text-xs flex items-center gap-1">
                <Globe className="w-3 h-3" />
                联网
              </span>
            )}
          </div>
        </div>

        {/* Messages */}
        <div
          ref={chatContainerRef}
          className="flex-1 overflow-y-auto p-4 space-y-4"
        >
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role !== "user" && (
                <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                  <Bot className="w-4 h-4 text-blue-600" />
                </div>
              )}
              <div
                className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-white border border-slate-200 text-slate-800"
                }`}
              >
                {msg.isStreaming && !msg.content ? (
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">思考中...</span>
                  </div>
                ) : (
                  <div className="prose prose-sm max-w-none dark:prose-invert">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}

                {/* Sources */}
                {msg.sources &&
                  ((msg.sources.rag?.length ?? 0) > 0 ||
                    (msg.sources.web?.length ?? 0) > 0) && (
                    <div className="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
                      {(msg.sources.rag?.length ?? 0) > 0 && (
                        <span className="mr-2">
                          📚 {msg.sources.rag?.length} 个知识库结果
                        </span>
                      )}
                      {(msg.sources.web?.length ?? 0) > 0 && (
                        <span>🌐 {msg.sources.web?.length} 个网络结果</span>
                      )}
                    </div>
                  )}

                {/* Add to notebook */}
                {msg.role === "assistant" &&
                  msg.content &&
                  !msg.isStreaming && (
                    <button
                      onClick={() => handleAddToNotebook(msg.content)}
                      className="mt-2 text-xs text-slate-400 hover:text-blue-600 flex items-center gap-1"
                    >
                      <Book className="w-3 h-3" />
                      保存到笔记本
                    </button>
                  )}
              </div>
              {msg.role === "user" && (
                <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center shrink-0">
                  <User className="w-4 h-4 text-slate-600" />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Input */}
        <div className="p-4 bg-white border-t border-slate-200">
          <div className="max-w-3xl mx-auto flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) =>
                e.key === "Enter" && !e.shiftKey && handleSend()
              }
              placeholder="输入你的问题..."
              disabled={isLoading}
              className="flex-1 px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="px-5 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Add to Notebook Modal */}
      {showNotebookModal && (
        <AddToNotebookModal
          isOpen={showNotebookModal}
          onClose={() => setShowNotebookModal(false)}
          recordType="co_writer"
          title="保存对话内容"
          userQuery=""
          output={selectedMessageContent}
        />
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center">
          加载中...
        </div>
      }
    >
      <ChatPageContent />
    </Suspense>
  );
}
