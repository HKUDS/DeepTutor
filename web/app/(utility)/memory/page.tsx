"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, Eraser, Loader2, RefreshCw, Save, BookOpen, User } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppShell } from "@/context/AppShellContext";
import { apiUrl } from "@/lib/api";

const MarkdownRenderer = dynamic(() => import("@/components/common/MarkdownRenderer"), {
  ssr: false,
});

type MemoryFile = "summary" | "profile";

interface MemoryData {
  summary: string;
  profile: string;
  summary_updated_at: string | null;
  profile_updated_at: string | null;
}

const TABS: { key: MemoryFile; label: string; icon: typeof Brain; hint: string; placeholder: string }[] = [
  {
    key: "summary",
    label: "Memory Summary",
    icon: BookOpen,
    hint: "Running summary of the learning journey. Auto-updated after conversations.",
    placeholder: "## Current Focus\n- ...\n\n## Completed Items\n- ...\n\n## Open Questions\n- ...",
  },
  {
    key: "profile",
    label: "Memory Profile",
    icon: User,
    hint: "User identity, preferences, and knowledge levels. Auto-updated after conversations.",
    placeholder: "## User Identity\n- ...\n\n## Learning Style\n- ...\n\n## Knowledge Level\n- ...\n\n## Preferences\n- ...",
  },
];

const EMPTY: MemoryData = {
  summary: "",
  profile: "",
  summary_updated_at: null,
  profile_updated_at: null,
};

function formatUpdatedAt(value: string | null, t: (key: string) => string): string {
  if (!value) return t("Not updated yet");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t("Unknown");
  return date.toLocaleString();
}

export default function MemoryPage() {
  const { t } = useTranslation();
  const { activeSessionId, language } = useAppShell();
  const [data, setData] = useState<MemoryData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<MemoryFile>("summary");
  const [activeView, setActiveView] = useState<"edit" | "preview">("edit");
  const [editors, setEditors] = useState<Record<MemoryFile, string>>({ summary: "", profile: "" });
  const [toast, setToast] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const tab = TABS.find((t) => t.key === activeTab)!;
  const tabLabel = t(tab.label);
  const editorValue = editors[activeTab];
  const hasChanges = editorValue !== data[activeTab];
  const updatedAt = data[`${activeTab}_updated_at` as keyof MemoryData] as string | null;

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const loadMemory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/v1/memory"));
      const d: MemoryData = await res.json();
      setData(d);
      setEditors({ summary: d.summary || "", profile: d.profile || "" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadMemory(); }, [loadMemory]);

  const saveMemory = useCallback(async () => {
    setSaving(true);
    try {
      const res = await fetch(apiUrl("/api/v1/memory"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: activeTab, content: editorValue }),
      });
      const d: MemoryData = await res.json();
      setData(d);
      setEditors((prev) => ({ ...prev, [activeTab]: d[activeTab] || "" }));
      setToast(t("{{name}} saved", { name: tabLabel }));
    } finally {
      setSaving(false);
    }
  }, [activeTab, editorValue, tabLabel, t]);

  const refreshMemory = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await fetch(apiUrl("/api/v1/memory/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: activeSessionId || undefined, language }),
      });
      const d: MemoryData = await res.json();
      setData(d);
      setEditors({ summary: d.summary || "", profile: d.profile || "" });
      setToast(t("Memory refreshed from session"));
    } finally {
      setRefreshing(false);
    }
  }, [activeSessionId, language]);

  const clearMemory = useCallback(async () => {
    if (!window.confirm(t("Clear {{name}}?", { name: tabLabel }))) return;
    setClearing(true);
    try {
      const res = await fetch(apiUrl("/api/v1/memory/clear"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: activeTab }),
      });
      const d: MemoryData = await res.json();
      setData(d);
      setEditors((prev) => ({ ...prev, [activeTab]: d[activeTab] || "" }));
      setToast(t("{{name}} cleared", { name: tabLabel }));
    } finally {
      setClearing(false);
    }
  }, [activeTab, tabLabel, t]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        void saveMemory();
      }
    },
    [saveMemory],
  );

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[960px] px-6 py-8">

        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
              {t("Memory")}
            </h1>
            {toast ? (
              <p className="mt-1 text-[13px] text-[var(--primary)] animate-fade-in">{toast}</p>
            ) : (
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                {hasChanges ? t("Unsaved changes") : t("All changes saved")}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={saveMemory}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
              {t("Save")}
            </button>
            <button
              onClick={refreshMemory}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              {t("Refresh")}
            </button>
            <button
              onClick={clearMemory}
              disabled={clearing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Eraser className="h-3 w-3" />}
              {t("Clear")}
            </button>
          </div>
        </div>

        {/* Tab selector */}
        <div className="mb-4 flex items-center gap-1 border-b border-[var(--border)]/50 pb-3">
          {TABS.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setActiveTab(item.key)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {t(item.label)}
              </button>
            );
          })}
        </div>

        {/* Meta & View toggle */}
        <div className="mb-6 flex items-center justify-between">
          <p className="max-w-lg text-[12px] text-[var(--muted-foreground)]">{t(tab.hint)}</p>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              {(["edit", "preview"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setActiveView(v)}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                    activeView === v
                      ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {v === "edit" ? t("Edit") : t("Preview")}
                </button>
              ))}
            </div>
            <span className="text-[12px] text-[var(--muted-foreground)]">
              {t("Updated")}: {formatUpdatedAt(updatedAt, t)}
            </span>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex min-h-[420px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : activeView === "edit" ? (
          <div>
            <textarea
              ref={textareaRef}
              value={editorValue}
              onChange={(e) => setEditors((prev) => ({ ...prev, [activeTab]: e.target.value }))}
              onKeyDown={handleKeyDown}
              spellCheck={false}
              className="min-h-[480px] w-full resize-none rounded-xl border border-[var(--border)] bg-transparent px-5 py-4 font-mono text-[13px] leading-7 text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              placeholder={tab.placeholder}
            />
            <p className="mt-2 text-[11px] text-[var(--muted-foreground)]/40">
              {t("Cmd+S to save · Markdown supported")}
            </p>
          </div>
        ) : editorValue.trim() ? (
          <div className="rounded-xl border border-[var(--border)] px-6 py-5">
            <MarkdownRenderer content={editorValue} variant="prose" className="text-[14px] leading-relaxed" />
          </div>
        ) : (
          <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
            <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
              <Brain size={18} />
            </div>
            <p className="text-[14px] font-medium text-[var(--foreground)]">
              {t("No {{name}} yet", { name: t(tab.label).toLowerCase() })}
            </p>
            <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
              {t("Refresh from a session or write directly in the editor.")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
