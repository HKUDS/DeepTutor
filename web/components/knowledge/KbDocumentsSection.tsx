"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderInput, Loader2, RefreshCw, Upload } from "lucide-react";
import {
  listKnowledgeBaseFiles,
  type KnowledgeUploadPolicy,
} from "@/lib/knowledge-api";
import {
  kbIsUploadable,
  kbNeedsReindex,
  providerUsesEmbeddingMetadata,
  resolveKbStatus,
  resolveProgressPercent,
  uploadPolicyForProvider,
  validateFiles,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import type { HistoryEntry } from "@/hooks/useKnowledgeHistory";
import ProcessLogs from "@/components/common/ProcessLogs";
import FileDropZone from "./FileDropZone";
import KbIndexFailureBanner from "./KbIndexFailureBanner";
import KbUpdateHistory from "./KbUpdateHistory";

interface KbDocumentsSectionProps {
  kb: KnowledgeBase;
  uploadPolicy: KnowledgeUploadPolicy;
  task?: TaskState;
  history: HistoryEntry[];
  onClearHistory: () => void;
  onRetry?: () => Promise<void>;
  onUpload: (files: File[], destSubdir?: string) => Promise<void>;
}

/**
 * The "Add documents" tab. Focused on the incremental-upload flow: drop
 * zone, upload button, live process logs while a task runs, and a list of
 * past update events. The file list and preview live under the separate
 * "Files" tab to keep each surface single-purpose.
 */
export default function KbDocumentsSection({
  kb,
  uploadPolicy,
  task,
  history,
  onClearHistory,
  onRetry,
  onUpload,
}: KbDocumentsSectionProps) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [retrySubmitting, setRetrySubmitting] = useState(false);
  // Existing folders in this KB, offered as a destination for the batch.
  const [folders, setFolders] = useState<string[]>([]);
  const [destSubdir, setDestSubdir] = useState("");

  useEffect(() => {
    let cancelled = false;
    void listKnowledgeBaseFiles(kb.name)
      .then((entries) => {
        if (cancelled) return;
        setFolders(
          entries
            .filter((entry) => entry.type === "folder")
            .map((entry) => entry.name)
            .sort((a, b) => a.localeCompare(b)),
        );
      })
      .catch(() => {
        // A destination picker is an optional convenience; failing to list
        // folders just means the batch goes to the root as it always did.
        if (!cancelled) setFolders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [kb.name]);

  const uploadable = kbIsUploadable(kb);
  const needsReindex = kbNeedsReindex(kb);
  const status = resolveKbStatus(kb);
  const isError = status === "error";
  const provider =
    kb.statistics?.rag_provider || kb.metadata?.rag_provider || "llamaindex";
  const policyForProvider = uploadPolicyForProvider(uploadPolicy, provider);

  const isUploadingHere = task?.kind === "upload" && task.executing;
  const isIndexingHere =
    (task?.kind === "reindex" || task?.kind === "retry") && task.executing;
  const isRetryingHere = task?.kind === "retry" && task.executing;

  // An error-state KB is not locked: the user can drop the file(s) that failed
  // (Files tab) and upload replacements here, instead of being forced to
  // delete and rebuild the whole base. Uploads stay open unless a rebuild is
  // actively running; legacy/transition states remain genuinely blocked.
  const canUpload = uploadable || (isError && !isIndexingHere);

  const blockedReason = canUpload
    ? null
    : needsReindex
      ? t(
          "This knowledge base is in legacy index format and needs reindex before upload.",
        )
      : status !== "ready"
        ? t(
            "This knowledge base is currently {{status}} and cannot accept uploads yet.",
            { status: status.replaceAll("_", " ") },
          )
        : null;

  const selection = validateFiles(files, policyForProvider, t);
  const canRetry = Boolean(onRetry) && isError && !isIndexingHere;
  // Unsupported files are skipped (shown in the drop zone), not blocking, so a
  // picked folder with mixed content still uploads its supported members.
  const canSubmit =
    canUpload &&
    selection.validFiles.length > 0 &&
    !submitting &&
    !isUploadingHere;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onUpload(selection.validFiles, destSubdir || undefined);
      setFiles([]);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetry = async () => {
    if (!onRetry || !canRetry || retrySubmitting) return;
    setRetrySubmitting(true);
    try {
      await onRetry();
    } finally {
      setRetrySubmitting(false);
    }
  };

  const percent = resolveProgressPercent(kb.progress);
  const showTaskLogs =
    task?.kind === "upload" ||
    task?.kind === "create" ||
    task?.kind === "reindex" ||
    task?.kind === "retry";
  const taskLogTitle =
    task?.kind === "create"
      ? t("Create Process")
      : task?.kind === "retry"
        ? t("Retry Process")
        : task?.kind === "reindex"
          ? t("Re-index Process")
          : t("Upload Process");

  return (
    <div className="space-y-5">
      <div>
        <div className="text-[13px] font-medium text-[var(--foreground)]">
          {t("Add documents")}
        </div>
        <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            providerUsesEmbeddingMetadata(provider)
              ? "Drop files here to add them to this knowledge base. New files are indexed against the active embedding model."
              : "Drop files here",
          )}
        </p>
      </div>

      {blockedReason && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          {blockedReason}
        </div>
      )}

      {isError && !blockedReason && (
        <KbIndexFailureBanner
          kb={kb}
          action={
            onRetry ? (
              <button
                type="button"
                onClick={handleRetry}
                disabled={!canRetry || retrySubmitting}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-red-300 bg-red-100 px-2 py-1 text-[11.5px] font-medium text-red-800 transition-colors hover:bg-red-200 disabled:opacity-50 dark:border-red-800 dark:bg-red-950/50 dark:text-red-200"
              >
                {retrySubmitting || isRetryingHere ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                {retrySubmitting || isRetryingHere
                  ? t("Retrying…")
                  : t("Retry indexing")}
              </button>
            ) : undefined
          }
        />
      )}

      <FileDropZone
        files={files}
        onChange={setFiles}
        uploadPolicy={policyForProvider}
        disabled={!canUpload || isUploadingHere}
      />

      {folders.length > 0 && files.length > 0 && (
        <label className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
          <FolderInput size={13} strokeWidth={1.7} />
          <span>{t("Add to folder")}</span>
          <select
            value={destSubdir}
            onChange={(event) => setDestSubdir(event.target.value)}
            disabled={!canUpload || isUploadingHere}
            className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[12px] text-[var(--foreground)] disabled:opacity-40"
          >
            <option value="">{t("Knowledge base root")}</option>
            {folders.map((folder) => (
              <option key={folder} value={folder}>
                {folder}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting || isUploadingHere ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload size={14} />
          )}
          {t("Upload")}
        </button>
      </div>

      {showTaskLogs &&
        task &&
        (task.taskId || task.logs.length > 0 || task.executing) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
              <span>
                {task.label}
                {task.taskId ? ` · ${task.taskId}` : ""}
              </span>
              {task.executing && percent > 0 && (
                <span className="font-medium text-[var(--foreground)]">
                  {percent}%
                </span>
              )}
            </div>
            <ProcessLogs
              logs={task.logs}
              executing={task.executing}
              title={taskLogTitle}
            />
            {task.executing && (
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]/70">
                <div
                  className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                  style={{ width: `${Math.max(percent, 4)}%` }}
                />
              </div>
            )}
            {task.error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                  {task.error}
                </pre>
              </div>
            )}
          </div>
        )}

      <KbUpdateHistory entries={history} onClear={onClearHistory} />
    </div>
  );
}
