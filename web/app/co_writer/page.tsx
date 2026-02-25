"use client";

import CoWriterEditor from "@/components/CoWriterEditor";
import { Edit3 } from "lucide-react";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

export default function CoWriterPage() {
  const { uiSettings } = useGlobal();
  const t = (key: string) => getTranslation(uiSettings.language, key);

  return (
    <div className="h-screen animate-fade-in flex flex-col p-8">
      {/* Header */}
      <div className="mb-6 shrink-0">
        <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-3 mb-2">
          <Edit3 className="w-8 h-8 text-purple-600 dark:text-purple-400" />
          智能写作
        </h1>
        <p className="text-slate-500 dark:text-slate-400 text-sm mt-2">
          基于 AI 辅助内容创作的智能 Markdown 编辑器
        </p>
      </div>

      {/* Editor Container */}
      <div className="flex-1 min-h-0">
        <CoWriterEditor />
      </div>
    </div>
  );
}
