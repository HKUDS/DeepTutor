"use client";

/* eslint-disable react-hooks/exhaustive-deps */

import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  X,
  MessageCircle,
  User,
  Bot,
  Clock,
  Loader2,
  MessageSquare,
  ExternalLink,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp?: number;
  sources?: {
    rag?: Array<{ kb_name: string; content: string }>;
    web?: Array<{ url: string; title?: string }>;
  };
}

interface ChatSession {
  session_id: string;
  title: string;
  messages: ChatMessage[];
  settings?: {
    kb_name?: string;
    enable_rag?: boolean;
    enable_web_search?: boolean;
  };
  created_at: number;
  updated_at: number;
}

interface ChatSessionDetailProps {
  sessionId: string;
  onClose: () => void;
  onContinue: () => void;
}

export default function ChatSessionDetail({
  sessionId,
  onClose,
  onContinue,
}: ChatSessionDetailProps) {
  const { uiSettings } = useGlobal();
  const t = (key: string) => getTranslation(uiSettings.language, key);

  const [session, setSession] = useState<ChatSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  // Ensure we're on the client before rendering portal
  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  useEffect(() => {
    const fetchSession = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          apiUrl(`/api/v1/chat/sessions/${sessionId}`),
        );
        if (!response.ok) {
          throw new Error(t("Failed to load session"));
        }
        const data = await response.json();
        setSession(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("Unknown error"));
      } finally {
        setLoading(false);
      }
    };

    fetchSession();
  }, [sessionId]);

  // Handle escape key to close modal
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  // Don't render until mounted (client-side only)
  if (!mounted) return null;

  const modalContent = (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Modal */}
      <div
        className="relative bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col animate-in zoom-in-95 duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center shrink-0">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <MessageCircle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <h2 className="font-bold text-slate-900 dark:text-slate-100 text-lg">
                {session?.title || t("Chat History")}
              </h2>
              {session && (
                <p className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2">
                  <Clock className="w-3 h-3" />
                  {new Date(session.created_at * 1000).toLocaleString(
                    uiSettings.language === "zh" ? "zh-CN" : "en-US",
                  )}
                  <span className="mx-1">•</span>
                  {session.messages.length} {t("messages")}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-amber-500" />
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <p className="text-red-500 dark:text-red-400">{error}</p>
            </div>
          ) : session ? (
            <div className="space-y-4">
              {/* Settings Info */}
              {session.settings &&
                (session.settings.kb_name ||
                  session.settings.enable_rag ||
                  session.settings.enable_web_search) && (
                  <div className="flex flex-wrap gap-2 mb-4 pb-4 border-b border-slate-100 dark:border-slate-700">
                    {session.settings.kb_name && (
                      <span className="px-2.5 py-1 text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full">
                        {t("KB")}: {session.settings.kb_name}
                      </span>
                    )}
                    {session.settings.enable_rag && (
                      <span className="px-2.5 py-1 text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 rounded-full">
                        {t("RAG Enabled")}
                      </span>
                    )}
                    {session.settings.enable_web_search && (
                      <span className="px-2.5 py-1 text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-full">
                        {t("Web Search Enabled")}
                      </span>
                    )}
                  </div>
                )}

              {/* Messages */}
              {session.messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.role === "assistant" && (
                    <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center shrink-0">
                      <Bot className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                    </div>
                  )}
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                      msg.role === "user"
                        ? "bg-blue-500 text-white rounded-br-none"
                        : "bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-bl-none"
                    }`}
                  >
                    {msg.role === "user" ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-headings:my-2">
                        <ReactMarkdown
                          remarkPlugins={[remarkMath]}
                          rehypePlugins={[rehypeKatex]}
                        >
                          {processLatexContent(msg.content)}
                        </ReactMarkdown>
                      </div>
                    )}

                    {/* Sources */}
                    {msg.sources &&
                      (msg.sources.rag?.length || msg.sources.web?.length) && (
                        <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-600">
                          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">
                            {t("Sources")}:
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {msg.sources.rag?.map((src, i) => (
                              <span
                                key={`rag-${i}`}
                                className="px-2 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded"
                              >
                                📚 {src.kb_name}
                              </span>
                            ))}
                            {msg.sources.web?.map((src, i) => (
                              <a
                                key={`web-${i}`}
                                href={src.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-2 py-0.5 text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded hover:bg-purple-200 dark:hover:bg-purple-900/50 flex items-center gap-1"
                              >
                                🌐 {src.title || new URL(src.url).hostname}
                                <ExternalLink className="w-2.5 h-2.5" />
                              </a>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Timestamp */}
                    {msg.timestamp && (
                      <p
                        className={`text-xs mt-2 ${
                          msg.role === "user"
                            ? "text-blue-200"
                            : "text-slate-400 dark:text-slate-500"
                        }`}
                      >
                        {new Date(msg.timestamp * 1000).toLocaleTimeString(
                          uiSettings.language === "zh" ? "zh-CN" : "en-US",
                          { hour: "2-digit", minute: "2-digit" },
                        )}
                      </p>
                    )}
                  </div>
                  {msg.role === "user" && (
                    <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center shrink-0">
                      <User className="w-4 h-4 text-white" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 rounded-b-2xl flex justify-between items-center shrink-0">
          <button
            onClick={onClose}
            className="px-6 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl font-medium hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
          >
            {t("Close")}
          </button>
          <button
            onClick={onContinue}
            className="px-6 py-2.5 bg-amber-500 text-white rounded-xl font-medium hover:bg-amber-600 transition-colors flex items-center gap-2"
          >
            <MessageSquare className="w-4 h-4" />
            {t("Continue")}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
