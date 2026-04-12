"use client";

import { useRef, useEffect } from "react";
import { Bug, Loader2 } from "lucide-react";
import { useKaTeXInjection } from "../hooks";
import { useTranslation } from "react-i18next";

interface HTMLViewerProps {
  html: string;
  currentIndex: number;
  loadingMessage: string;
  onOpenDebugModal: () => void;
}

export default function HTMLViewer({
  html,
  currentIndex,
  loadingMessage,
  onOpenDebugModal,
}: HTMLViewerProps) {
  const { t } = useTranslation();
  const htmlFrameRef = useRef<HTMLIFrameElement>(null);
  const lastWrittenRef = useRef<string>("");
  const lastIndexRef = useRef<number>(currentIndex);
  const { injectKaTeX } = useKaTeXInjection();

  const sanitizeHtml = (rawHtml: string) =>
    rawHtml
      .replace(/<script(?![^>]*katex)[\s\S]*?>[\s\S]*?<\/script>/gi, "")
      .replace(/\son[a-z]+\s*=\s*(['"]).*?\1/gi, (match) => {
        if (/onload\s*=\s*(['"])renderMathInElement/i.test(match)) return match;
        return "";
      })
      .replace(/\s(href|src)\s*=\s*(['"])javascript:[\s\S]*?\2/gi, "");

  useEffect(() => {
    if (currentIndex !== lastIndexRef.current) {
      lastWrittenRef.current = "";
      lastIndexRef.current = currentIndex;
    }
  }, [currentIndex]);

  useEffect(() => {
    if (!html) return;

    const injected = injectKaTeX(html);
    const htmlWithKaTeX = sanitizeHtml(injected);

    if (lastWrittenRef.current === htmlWithKaTeX) {
      return;
    }

    const timer = setTimeout(() => {
      if (htmlFrameRef.current) {
        const iframe = htmlFrameRef.current;
        iframe.srcdoc = htmlWithKaTeX;
        lastWrittenRef.current = htmlWithKaTeX;
      }
    }, 100);

    return () => clearTimeout(timer);
  }, [html, currentIndex, injectKaTeX]);

  if (!html) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-white dark:bg-slate-800 rounded-b-2xl border border-t-0 border-slate-200 dark:border-slate-700">
        <Loader2 className="w-12 h-12 text-indigo-400 dark:text-indigo-500 animate-spin mb-4" />
        <p className="text-slate-500 dark:text-slate-400">
          {loadingMessage || t("Loading learning content...")}
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 bg-white dark:bg-slate-800 rounded-b-2xl shadow-sm border border-t-0 border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden relative">
      <button
        onClick={onOpenDebugModal}
        className="absolute top-4 right-4 z-10 p-2 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg transition-colors shadow-sm"
        title={t("Fix HTML")}
      >
        <Bug className="w-4 h-4 text-slate-600 dark:text-slate-300" />
      </button>

      <iframe
        ref={htmlFrameRef}
        className="w-full flex-1 border-0"
        title={t("Interactive Learning Content")}
        sandbox="allow-scripts allow-same-origin"
      />
    </div>
  );
}
