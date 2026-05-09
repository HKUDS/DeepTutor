"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Brain,
  Eraser,
  Loader2,
  RefreshCw,
  Save,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppShell } from "@/context/AppShellContext";
import { apiFetch, apiUrl } from "@/lib/api";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

type MemoryFile = "summary" | "profile";

interface MemoryData {
  summary: string;
  profile: string;
  summary_updated_at: string | null;
  profile_updated_at: string | null;
}

interface MemoryApiData extends MemoryData {
  changed?: boolean;
}

const TABS: {
  key: MemoryFile;
  label: string;
  icon: typeof Brain;
  hint: string;
  placeholder: string;
}[] = [
  {
    key: "summary",
    label: "Summary",
    icon: BookOpen,
    hint: "Running summary of the learning journey. Auto-updated after conversations.",
    placeholder:
      "## Current Focus\n- ...\n\n## Accomplishments\n- ...\n\n## Open Questions\n- ...",
  },
  {
    key: "profile",
    label: "Profile",
    icon: User,
    hint: "User identity, preferences, and knowledge levels. Auto-updated after conversations.",
    placeholder:
      "## Identity\n- ...\n\n## Learning Style\n- ...\n\n## Knowledge Level\n- ...\n\n## Preferences\n- ...",
  },
];

const EMPTY: MemoryData = {
  summary: "",
  profile: "",
  summary_updated_at: null,
  profile_updated_at: null,
};

function formatUpdatedAt(
  value: string | null,
  t: (key: string) => string,
): string {
  if (!value) return t("Not updated yet");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t("Unknown");
  return date.toLocaleString();
}

async function readMemoryResponse(res: Response): Promise<MemoryApiData> {
  const payload = (await res.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  if (!res.ok) {
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : "Memory request failed",
    );
  }
  return payload as MemoryApiData;
}

export default function MemorySection() {
  const { t } = useTranslation();
  const { activeSessionId, language } = useAppShell();
  const [data, setData] = useState<MemoryData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<MemoryFile>("summary");
  const [activeView, setActiveView] = useState<"edit" | "preview">("edit");
  const [editors, setEditors] = useState<Record<MemoryFile, string>>({
    summary: "",
    profile: "",
  });
  const [toast, setToast] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const tab = TABS.find((tabItem) => tabItem.key === activeTab)!;
  const editorValue = editors[activeTab];
  const hasChanges = editorValue !== data[activeTab];
  const updatedAt = data[`${activeTab}_updated_at` as keyof MemoryData] as
    | string
    | null;

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const loadMemory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory"));
      const d = await readMemoryResponse(res);
      setData(d);
      setEditors({ summary: d.summary || "", profile: d.profile || "" });
    } catch (error) {
      setToast(
        error instanceof Error ? error.message : t("Memory request failed"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadMemory();
  }, [loadMemory]);

  const saveMemory = useCallback(async () => {
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: activeTab, content: editorValue }),
      });
      const d = await readMemoryResponse(res);
      setData(d);
      setEditors((prev) => ({ ...prev, [activeTab]: d[activeTab] || "" }));
      setToast(t("{{label}} saved", { label: t(tab.label) }));
    } catch (error) {
      setToast(
        error instanceof Error ? error.message : t("Memory save failed"),
      );
    } finally {
      setSaving(false);
    }
  }, [activeTab, editorValue, t, tab.label]);

  const refreshMemory = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeSessionId || undefined,
          language,
        }),
      });
      const d = await readMemoryResponse(res);
      setData(d);
      setEditors({ summary: d.summary || "", profile: d.profile || "" });
      setToast(
        d.changed === false
          ? t("Memory checked; no long-term updates")
          : t("Memory refreshed from session"),
      );
    } catch (error) {
      setToast(
        error instanceof Error ? error.message : t("Memory refresh failed"),
      );
    } finally {
      setRefreshing(false);
    }
  }, [activeSessionId, language, t]);

  const clearMemory = useCallback(async () => {
    if (!window.confirm(t("Clear {{label}}?", { label: t(tab.label) }))) return;
    setClearing(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory/clear"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: activeTab }),
      });
      const d = await readMemoryResponse(res);
      setData(d);
      setEditors((prev) => ({ ...prev, [activeTab]: d[activeTab] || "" }));
      setToast(t("{{label}} cleared", { label: t(tab.label) }));
    } catch (error) {
      setToast(
        error instanceof Error ? error.message : t("Memory clear failed"),
      );
    } finally {
      setClearing(false);
    }
  }, [activeTab, t, tab.label]);

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
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={Brain}
        title={t("Memory")}
        description={t(
          "Long-form memory the assistant carries across sessions — your running summary and learner profile.",
        )}
        meta={
          toast ? (
            <span className="rounded-full border border-[var(--primary)]/30 bg-[var(--primary)]/10 px-2 py-0.5 text-[10.5px] font-medium text-[var(--primary)]">
              {toast}
            </span>
          ) : (
            <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
              {hasChanges ? t("Unsaved changes") : t("All changes saved")}
            </span>
          )
        }
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={saveMemory}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {saving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              {t("Save")}
            </button>
            <button
              onClick={refreshMemory}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {refreshing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {t("Refresh")}
            </button>
            <button
              onClick={clearMemory}
              disabled={clearing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {clearing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Eraser className="h-3 w-3" />
              )}
              {t("Clear")}
            </button>
          </div>
        }
      />

      {/* Tab selector */}
      <div className="flex items-center gap-1 border-b border-[var(--border)]/50 pb-3">
        {TABS.map((tabItem) => {
          const Icon = tabItem.icon;
          const active = activeTab === tabItem.key;
          return (
            <button
              key={tabItem.key}
              onClick={() => setActiveTab(tabItem.key)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                active
                  ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t(tabItem.label)}
            </button>
          );
        })}
      </div>

      {/* Meta & View toggle */}
      <div className="flex items-center justify-between">
        <p className="max-w-lg text-[12px] text-[var(--muted-foreground)]">
          {t(tab.hint)}
        </p>
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
            onChange={(e) =>
              setEditors((prev) => ({ ...prev, [activeTab]: e.target.value }))
            }
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
          <MarkdownRenderer
            content={editorValue}
            variant="prose"
            className="text-[14px] leading-relaxed"
          />
        </div>
      ) : (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
            <Brain size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No {{label}} yet", { label: t(tab.label).toLowerCase() })}
          </p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
            {t("Refresh from a session or write directly in the editor.")}
          </p>
        </div>
      )}
    </div>
  );
}
