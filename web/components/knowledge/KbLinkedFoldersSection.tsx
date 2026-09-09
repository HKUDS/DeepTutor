"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  FolderSync,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import {
  formatKnowledgeTimestamp,
  resolveProgressPercent,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type {
  LinkedFolderInfo,
  SyncFolderResponse,
} from "@/features/knowledge/model/types";
import { listLinkedFolders } from "@/features/knowledge/api/folders";
import ProcessLogs from "@/components/common/ProcessLogs";
import LinkFolderModal from "./LinkFolderModal";

interface KbLinkedFoldersSectionProps {
  kb: KnowledgeBase;
  task?: TaskState;
  onLinkFolder: (folderPath: string) => Promise<void>;
  onUnlinkFolder: (folderId: string) => Promise<void>;
  onSyncFolder: (folderId: string) => Promise<SyncFolderResponse>;
}

export default function KbLinkedFoldersSection({
  kb,
  task,
  onLinkFolder,
  onUnlinkFolder,
  onSyncFolder,
}: KbLinkedFoldersSectionProps) {
  const { t } = useTranslation();
  const [folders, setFolders] = useState<LinkedFolderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [unlinkingId, setUnlinkingId] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [activeSyncFolderId, setActiveSyncFolderId] = useState<string | null>(
    null,
  );
  const [syncResults, setSyncResults] = useState<
    Record<string, SyncFolderResponse>
  >({});
  const observedSyncTaskRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    setLoading(true);
    setLoadError(null);
    setError(null);
    try {
      const result = await listLinkedFolders(kb.name, {
        signal: controller.signal,
      });
      setFolders(result);
      setError(null);
    } catch (err) {
      let message: string;
      if (err instanceof DOMException && err.name === "AbortError") {
        message = t("Timed out loading linked folders. Click retry.");
      } else {
        message = err instanceof Error ? err.message : String(err);
      }
      setLoadError(message);
      setError(message);
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }, [kb.name, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A sync request returns before indexing completes. Refresh only after the
  // shared task stream reaches a terminal state so last_sync comes from disk.
  useEffect(() => {
    if (task?.kind !== "sync" || !task.taskId) return;
    if (task.executing) {
      observedSyncTaskRef.current = task.taskId;
      return;
    }
    if (observedSyncTaskRef.current !== task.taskId) return;
    observedSyncTaskRef.current = null;
    setActiveSyncFolderId(null);
    void refresh();
  }, [refresh, task?.executing, task?.kind, task?.taskId]);

  const activeSync =
    syncingId !== null || (task?.kind === "sync" && task.executing);
  const readOnly = Boolean(kb.read_only);

  const handleLink = async (folderPath: string) => {
    setError(null);
    await onLinkFolder(folderPath);
    await refresh();
  };

  const handleUnlink = async (folder: LinkedFolderInfo) => {
    if (
      !window.confirm(
        t(
          "Unlinking stops future syncs. Files already imported remain in this knowledge base.",
        ),
      )
    ) {
      return;
    }
    setUnlinkingId(folder.id);
    setError(null);
    try {
      await onUnlinkFolder(folder.id);
      setFolders((current) => current.filter((item) => item.id !== folder.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUnlinkingId(null);
    }
  };

  const handleSync = async (folder: LinkedFolderInfo) => {
    setSyncingId(folder.id);
    setActiveSyncFolderId(folder.id);
    setError(null);
    setSyncResults((current) => {
      const next = { ...current };
      delete next[folder.id];
      return next;
    });
    let queued = false;
    try {
      const result = await onSyncFolder(folder.id);
      setSyncResults((current) => ({ ...current, [folder.id]: result }));
      if (!result.task_id) {
        setActiveSyncFolderId(null);
        await refresh();
      } else {
        queued = true;
        // Remember the task before React receives the shared progress state;
        // a very fast task can reach its terminal event between these renders.
        observedSyncTaskRef.current = result.task_id;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncingId(null);
      if (!queued) setActiveSyncFolderId(null);
    }
  };

  const retry = () => {
    setLoadError(null);
    void refresh();
  };

  if (folders.length === 0 && (loading || loadError)) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10">
        {loadError ? (
          <>
            <p
              role="alert"
              className="text-center text-[12px] text-red-600 dark:text-red-400"
            >
              {loadError}
            </p>
            <button
              type="button"
              onClick={retry}
              disabled={loading}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <RefreshCw className="h-3 w-3" />
              {t("Retry")}
            </button>
          </>
        ) : (
          <Loader2
            className="h-4 w-4 animate-spin text-[var(--muted-foreground)]"
            aria-label={t("Loading linked folders")}
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
            <FolderSync className="h-4 w-4 text-[var(--muted-foreground)]" />
            {t("Linked folders")}
          </div>
          <p className="mt-0.5 max-w-2xl text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Keep a local folder as a document source and sync new or modified supported files when you choose.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setLinkOpen(true)}
          disabled={readOnly || activeSync}
          className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-45"
          title={
            readOnly
              ? t("Assigned knowledge bases are read-only.")
              : activeSync
                ? t("Wait for the current sync to finish.")
                : undefined
          }
        >
          <FolderSync className="h-3.5 w-3.5" />
          {t("Link folder")}
        </button>
      </div>

      {readOnly && (
        <div className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11.5px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300">
          {t("This knowledge base is read-only. Linked folders can be viewed but not changed.")}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-200 bg-red-50/60 p-2.5 text-[11.5px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300"
        >
          <span className="min-w-0 flex-1 break-words">{error}</span>
          {loadError && (
            <button
              type="button"
              onClick={retry}
              disabled={loading}
              className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-red-300 px-2.5 py-1 text-[12px] font-medium transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-950/50"
            >
              <RefreshCw className="h-3 w-3" />
              {t("Retry")}
            </button>
          )}
        </div>
      )}

      {task?.kind === "sync" &&
        (task.taskId || task.logs.length > 0 || task.executing) && (
          <SyncProgress task={task} progress={kb.progress} />
        )}

      {folders.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-10 text-center">
          <FolderSync className="mx-auto mb-2 h-7 w-7 text-[var(--muted-foreground)]" />
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t('No linked folders yet. Click "Link folder" to add a source.')}
          </p>
          <button
            type="button"
            onClick={() => setLinkOpen(true)}
            disabled={readOnly || activeSync}
            className="mt-3 inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <FolderSync className="h-3.5 w-3.5" />
            {t("Link folder")}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {folders.map((folder) => (
            <LinkedFolderCard
              key={folder.id}
              folder={folder}
              result={syncResults[folder.id]}
              readOnly={readOnly}
              busy={activeSync}
              syncing={
                activeSync &&
                (activeSyncFolderId === null || activeSyncFolderId === folder.id)
              }
              unlinking={unlinkingId === folder.id}
              onSync={() => void handleSync(folder)}
              onUnlink={() => void handleUnlink(folder)}
            />
          ))}
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Sync now imports new or modified supported files. Deleted or renamed source files are not removed yet.",
        )}
      </p>

      <LinkFolderModal
        isOpen={linkOpen}
        onClose={() => setLinkOpen(false)}
        onSubmit={handleLink}
      />
    </div>
  );
}

function LinkedFolderCard({
  folder,
  result,
  readOnly,
  busy,
  syncing,
  unlinking,
  onSync,
  onUnlink,
}: {
  folder: LinkedFolderInfo;
  result?: SyncFolderResponse;
  readOnly: boolean;
  busy: boolean;
  syncing: boolean;
  unlinking: boolean;
  onSync: () => void;
  onUnlink: () => void;
}) {
  const { t } = useTranslation();
  const addedAt = formatKnowledgeTimestamp(folder.added_at);
  const lastSync = formatKnowledgeTimestamp(folder.last_sync ?? undefined);
  const actionDisabled = readOnly || busy || unlinking;

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-start gap-2">
            <FolderSync className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
            <code
              title={folder.path}
              className="min-w-0 break-all text-[12.5px] font-medium text-[var(--foreground)]"
            >
              {folder.path}
            </code>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
            <span>
              {t("{{count}} tracked files", { count: folder.file_count })}
            </span>
            {addedAt && <span>{t("Linked {{time}}", { time: addedAt })}</span>}
            <span>
              {t("Last successful sync")}: {lastSync || t("Never synced")}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onSync}
            disabled={actionDisabled}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-2 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-45"
            title={
              readOnly
                ? t("Assigned knowledge bases are read-only.")
                : busy
                  ? t("Wait for the current sync to finish.")
                  : t("Check this folder for new or modified files")
            }
          >
            {syncing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {syncing ? t("Syncing…") : t("Sync now")}
          </button>
          <button
            type="button"
            onClick={onUnlink}
            disabled={actionDisabled}
            aria-label={t("Unlink {{path}}", { path: folder.path })}
            title={t("Unlink folder")}
            className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md border border-transparent px-2 py-2 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-45 dark:hover:bg-red-950/30"
          >
            {unlinking ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>

      {result && (
        <div
          role="status"
          aria-live="polite"
          className="mt-3 flex items-start gap-2 rounded-md border border-emerald-200 bg-emerald-50/70 px-2.5 py-2 text-[11.5px] text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300"
        >
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">
            {result.task_id
              ? `${t("Queued {{count}} files for indexing.", {
                  count: result.file_count,
                })} ${t("{{new}} new, {{modified}} modified.", {
                  new: result.new_files,
                  modified: result.modified_files,
                })}`
              : result.new_files || result.modified_files
                ? t("{{new}} new, {{modified}} modified.", {
                    new: result.new_files,
                    modified: result.modified_files,
                  })
                : result.message}
          </span>
        </div>
      )}
    </div>
  );
}

function SyncProgress({
  task,
  progress,
}: {
  task: TaskState;
  progress?: KnowledgeBase["progress"];
}) {
  const { t } = useTranslation();
  const percent = resolveProgressPercent(progress);

  return (
    <div
      className="space-y-2"
      role="status"
      aria-live="polite"
      aria-busy={task.executing}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--muted-foreground)]">
        <span>{t(task.label || "Sync linked folder")}</span>
        {task.executing && percent > 0 && (
          <span className="font-medium text-[var(--foreground)]">
            {percent}%
          </span>
        )}
      </div>
      <ProcessLogs
        logs={task.logs}
        executing={task.executing}
        title={t("Sync Process")}
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
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
        >
          <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
            {task.error}
          </pre>
        </div>
      )}
    </div>
  );
}
