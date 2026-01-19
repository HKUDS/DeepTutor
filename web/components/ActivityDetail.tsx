"use client";

import { useState, useEffect, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { X, FileText, HelpCircle, Search, Clock, Database } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { processLatexContent } from "@/lib/latex";

// Hook to safely detect client-side rendering
const emptySubscribe = () => () => {};
function useIsClient() {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}

interface ActivityDetailProps {
  activity: any;
  onClose: () => void;
}

export default function ActivityDetail({
  activity,
  onClose,
}: ActivityDetailProps) {
  const mounted = useIsClient();

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

  if (!activity || !mounted) return null;

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
            <div
              className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                activity.type === "solve"
                  ? "bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                  : activity.type === "question"
                    ? "bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400"
                    : "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
              }`}
            >
              {activity.type === "solve" && <HelpCircle className="w-5 h-5" />}
              {activity.type === "question" && <FileText className="w-5 h-5" />}
              {activity.type === "research" && <Search className="w-5 h-5" />}
            </div>
            <div>
              <h2 className="font-bold text-slate-900 dark:text-slate-100 text-lg">
                Activity Details
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <Clock className="w-3 h-3" />
                {new Date(activity.timestamp * 1000).toLocaleString()}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Meta Info */}
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-700">
              <div className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
                Type
              </div>
              <div className="font-medium text-slate-900 dark:text-slate-100 capitalize">
                {activity.type}
              </div>
            </div>
            <div className="p-4 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-700">
              <div className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
                Knowledge Base
              </div>
              <div className="font-medium text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <Database className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                {activity.content?.kb_name || "Unknown"}
              </div>
            </div>
          </div>

          {/* Activity Specific Content */}

          {/* 1. SOLVE */}
          {activity.type === "solve" && (
            <>
              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Question
                </h3>
                <div className="p-4 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 leading-relaxed">
                  {activity.content.question}
                </div>
              </div>
              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Final Answer
                </h3>
                <div className="p-6 bg-white dark:bg-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
                  <div className="prose prose-slate dark:prose-invert max-w-none prose-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {processLatexContent(activity.content.answer)}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* 2. QUESTION */}
          {activity.type === "question" && (
            <>
              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Parameters
                </h3>
                <div className="grid grid-cols-3 gap-3">
                  <div className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/50">
                    <span className="font-bold">Topic:</span>{" "}
                    {activity.content?.requirement?.knowledge_point || "N/A"}
                  </div>
                  <div className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/50">
                    <span className="font-bold">Difficulty:</span>{" "}
                    {activity.content?.requirement?.difficulty || "N/A"}
                  </div>
                  <div className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/50">
                    <span className="font-bold">Type:</span>{" "}
                    {activity.content?.requirement?.question_type ||
                      activity.content?.question?.question_type ||
                      "N/A"}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Generated Question
                </h3>
                <div className="p-6 bg-white dark:bg-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm space-y-4">
                  <p className="text-lg font-medium text-slate-900 dark:text-slate-100">
                    {activity.content?.question?.content ||
                      activity.content?.question?.question ||
                      "No question content"}
                  </p>

                  {/* Handle options as object (A, B, C, D format) or array */}
                  {activity.content?.question?.options && (
                    <div className="space-y-2">
                      {Array.isArray(activity.content.question.options)
                        ? // Array format
                          activity.content.question.options.map(
                            (opt: string, i: number) => (
                              <div
                                key={i}
                                className="p-3 border border-slate-100 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-700 dark:text-slate-300"
                              >
                                <span className="font-bold text-purple-600 dark:text-purple-400 mr-2">
                                  {String.fromCharCode(65 + i)}.
                                </span>
                                {opt}
                              </div>
                            ),
                          )
                        : // Object format { "A": "...", "B": "..." }
                          Object.entries(activity.content.question.options).map(
                            ([key, value]) => (
                              <div
                                key={key}
                                className="p-3 border border-slate-100 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-700 dark:text-slate-300"
                              >
                                <span className="font-bold text-purple-600 dark:text-purple-400 mr-2">
                                  {key}.
                                </span>
                                {value as string}
                              </div>
                            ),
                          )}
                    </div>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="font-bold text-green-700 dark:text-green-400">
                  Correct Answer & Explanation
                </h3>
                <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-100 dark:border-green-800 text-green-800 dark:text-green-300 space-y-2">
                  <p className="font-bold">
                    Answer:{" "}
                    {activity.content?.question?.answer ||
                      activity.content?.question?.correct_answer ||
                      "N/A"}
                  </p>
                  <p className="text-sm leading-relaxed">
                    {activity.content?.question?.explanation ||
                      "No explanation provided"}
                  </p>
                </div>
              </div>
            </>
          )}

          {/* 3. RESEARCH */}
          {activity.type === "research" && (
            <>
              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Topic
                </h3>
                <div className="text-lg font-medium text-slate-800 dark:text-slate-200">
                  {activity.content.topic}
                </div>
              </div>
              <div className="space-y-2">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Report Preview
                </h3>
                <div className="p-6 bg-white dark:bg-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm max-h-96 overflow-y-auto font-mono text-xs text-slate-600 dark:text-slate-300">
                  {activity.content.report}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 rounded-b-2xl flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="px-6 py-2.5 bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 rounded-xl font-medium hover:bg-slate-800 dark:hover:bg-slate-200 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
