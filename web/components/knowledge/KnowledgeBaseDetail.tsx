"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Database,
  FileText,
  Layers,
  Settings as SettingsIcon,
  Star,
  Upload,
} from "lucide-react";
import type { KnowledgeUploadPolicy } from "@/lib/knowledge-api";
import {
  formatKnowledgeTimestamp,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import type { HistoryEntry } from "@/hooks/useKnowledgeHistory";
import KbStatusBadge from "./KbStatusBadge";
import KbFilesTab from "./KbFilesTab";
import KbDocumentsSection from "./KbDocumentsSection";
import KbIndexVersionsSection from "./KbIndexVersionsSection";
import KbSettingsSection from "./KbSettingsSection";

type DetailSection = "files" | "add" | "versions" | "settings";

interface KnowledgeBaseDetailProps {
  kb: KnowledgeBase | null;
  uploadPolicy: KnowledgeUploadPolicy;
  task?: TaskState;
  history: HistoryEntry[];
  onCreate: () => void;
  onUpload: (kbName: string, files: File[]) => Promise<void>;
  onReindex: (kbName: string) => Promise<void>;
  onSetDefault: (kbName: string) => Promise<void>;
  onDelete: (kbName: string) => Promise<void>;
  onClearHistory: (kbName: string) => void;
}

const SECTIONS: {
  key: DetailSection;
  label: string;
  Icon: typeof FileText;
}[] = [
  { key: "files", label: "Files", Icon: FileText },
  { key: "add", label: "Add documents", Icon: Upload },
  { key: "versions", label: "Index versions", Icon: Layers },
  { key: "settings", label: "Settings", Icon: SettingsIcon },
];

/** Sections that fill the detail body edge-to-edge (no max-w wrapper). */
const FULL_BLEED_SECTIONS = new Set<DetailSection>(["files"]);

export default function KnowledgeBaseDetail({
  kb,
  uploadPolicy,
  task,
  history,
  onCreate,
  onUpload,
  onReindex,
  onSetDefault,
  onDelete,
  onClearHistory,
}: KnowledgeBaseDetailProps) {
  const { t } = useTranslation();
  const [section, setSection] = useState<DetailSection>("files");

  if (!kb) {
    return (
      <main className="flex flex-1 items-center justify-center bg-[var(--background)] p-6">
        <div className="max-w-sm rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--muted)] text-[var(--muted-foreground)]">
            <Database className="h-5 w-5" />
          </div>
          <div className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No knowledge base selected")}
          </div>
          <p className="mx-auto mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Pick a knowledge base from the list, or create a new one to get started.",
            )}
          </p>
          <button
            type="button"
            onClick={onCreate}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            {t("Create your first knowledge base")}
          </button>
        </div>
      </main>
    );
  }

  const meta = kb.metadata || {};
  const provider = kb.statistics?.rag_provider || "llamaindex";
  const embeddingLabel = meta.embedding_model
    ? typeof meta.embedding_dim === "number"
      ? `${meta.embedding_model} · ${meta.embedding_dim}${t("d")}`
      : meta.embedding_model
    : t("Default embedding");
  const updatedLabel =
    formatKnowledgeTimestamp(meta.last_updated) || t("Unknown time");
  const lastIndexedLabel = formatKnowledgeTimestamp(meta.last_indexed_at);

  const isReindexingLocally =
    task?.kind === "reindex" && task.executing === true;

  const fullBleed = FULL_BLEED_SECTIONS.has(section);

  return (
    <main className="flex h-full flex-1 flex-col overflow-hidden bg-[var(--background)]">
      {/* Header */}
      <div className="border-b border-[var(--border)] bg-[var(--card)] px-6 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-[18px] font-semibold tracking-tight text-[var(--foreground)]">
                {kb.name}
              </h1>
              {kb.is_default && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                  <Star className="h-3 w-3" fill="currentColor" />
                  {t("Default")}
                </span>
              )}
              {kb.assigned && (
                <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                  {kb.provenance_label || t("Assigned by admin")}
                </span>
              )}
              <KbStatusBadge
                kb={kb}
                isReindexingLocally={isReindexingLocally}
              />
            </div>
            <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
              {provider} · {embeddingLabel} · {t("Updated")} {updatedLabel}
              {lastIndexedLabel
                ? ` · ${t("Last indexed")} ${lastIndexedLabel}`
                : ""}
            </p>
          </div>
        </div>

        {/* Section nav */}
        <nav className="-mb-3 mt-3 flex gap-1 overflow-x-auto">
          {SECTIONS.map(({ key, label, Icon }) => {
            const active = section === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setSection(key)}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-t-md px-3 py-2 text-[12.5px] font-medium transition-colors ${
                  active
                    ? "border-b-2 border-[var(--primary)] text-[var(--foreground)]"
                    : "border-b-2 border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={13} />
                {t(label)}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {section === "files" ? (
          <KbFilesTab key={kb.name} kb={kb} task={task} />
        ) : (
          <div className="h-full overflow-y-auto px-6 py-5">
            <div className={fullBleed ? "" : "mx-auto max-w-3xl"}>
              {section === "add" && (
                <KbDocumentsSection
                  kb={kb}
                  uploadPolicy={uploadPolicy}
                  task={task}
                  history={history}
                  onClearHistory={() => onClearHistory(kb.name)}
                  onUpload={(files) =>
                    kb.read_only ? Promise.resolve() : onUpload(kb.name, files)
                  }
                />
              )}
              {section === "versions" && (
                <KbIndexVersionsSection
                  kb={kb}
                  task={task}
                  onReindex={() =>
                    kb.read_only ? Promise.resolve() : onReindex(kb.name)
                  }
                />
              )}
              {section === "settings" && (
                <KbSettingsSection
                  kb={kb}
                  onSetDefault={() =>
                    kb.read_only ? Promise.resolve() : onSetDefault(kb.name)
                  }
                  onDelete={() =>
                    kb.read_only ? Promise.resolve() : onDelete(kb.name)
                  }
                />
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
