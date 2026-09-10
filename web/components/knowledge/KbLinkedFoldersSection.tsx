"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FolderSync,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import {
  linkFolder,
  listLinkedFolders,
  syncLinkedFolder,
  unlinkFolder,
  type LinkedFolderInfo,
} from "@/features/knowledge/api/sources";
import { useKnowledgeProgress } from "@/hooks/useKnowledgeProgress";
import { formatKnowledgeTimestamp } from "@/lib/knowledge-helpers";

interface KbLinkedFoldersSectionProps {
  kbName: string;
  readOnly?: boolean;
}

export default function KbLinkedFoldersSection({
  kbName,
  readOnly = false,
}: KbLinkedFoldersSectionProps) {
  const { t } = useTranslation();
  const [folders, setFolders] = useState<LinkedFolderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [pathInput, setPathInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await listLinkedFolders(kbName);
      setFolders(list);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [kbName]);

  const handleTaskComplete = useCallback(() => {
    void refresh();
  }, [refresh]);

  const { startTask, tasksByKb, progressByKb } = useKnowledgeProgress({
    onComplete: handleTaskComplete,
  });
  const task = tasksByKb[kbName];
  const progress = progressByKb[kbName];

  useEffect(() => {
    let active = true;
    void (async () => {
      await refresh();
      if (!active) return;
    })();
    return () => {
      active = false;
    };
  }, [refresh]);

  const handleLink = async () => {
    const folderPath = pathInput.trim();
    if (!folderPath || readOnly) return;

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await linkFolder(kbName, folderPath);
      setPathInput("");
      setShowForm(false);
      setNotice(t("Folder linked."));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleUnlink = async (folderId: string) => {
    if (readOnly) return;
    setRemovingId(folderId);
    setError(null);
    setNotice(null);
    try {
      await unlinkFolder(kbName, folderId);
      setNotice(t("Folder unlinked."));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRemovingId(null);
    }
  };

  const handleSync = async (folder: LinkedFolderInfo) => {
    setSyncingId(folder.id);
    setError(null);
    setNotice(null);
    try {
      const result = await syncLinkedFolder(kbName, folder.id);
      if (result.file_count === 0) {
        setNotice(t("No new or modified files to sync."));
      } else if (result.task_id) {
        startTask({
          kbName,
          taskId: result.task_id,
          kind: "folder_sync",
          label: t("Syncing {{count}} changed file(s).", {
            count: result.file_count,
          }),
          seed: {
            stage: "processing",
            message: t("Syncing {{count}} changed file(s).", {
              count: result.file_count,
            }),
          },
        });
      } else {
        setNotice(
          t("Sync started for {{count}} changed file(s).", {
            count: result.file_count,
          }),
        );
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  const percent =
    typeof progress?.percent === "number"
      ? progress.percent
      : typeof progress?.progress_percent === "number"
        ? progress.progress_percent
        : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {t("Linked folders")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t(
              "Keep a local folder as a source. Uploads copy files once; links remember the source for manual synchronization.",
            )}
          </p>
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setShowForm((value) => !value)}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            <Plus className="h-3 w-3" />
            {t("Link folder")}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50/60 p-2.5 text-[11.5px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
          {error}
        </div>
      )}
      {notice && !error && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50/60 p-2.5 text-[11.5px] text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300">
          {notice}
        </div>
      )}

      {showForm && !readOnly && (
        <form
          className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void handleLink();
          }}
        >
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--muted-foreground)]">
              {t("Folder path")}
            </span>
            <input
              type="text"
              value={pathInput}
              aria-label={t("Folder path")}
              onChange={(event) => setPathInput(event.target.value)}
              placeholder={t("~/Documents/research-notes")}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 font-mono text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={submitting || !pathInput.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
              {t("Link")}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              {t("Cancel")}
            </button>
          </div>
        </form>
      )}

      {folders.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] py-8 text-center">
          <FolderSync className="mx-auto mb-2 h-6 w-6 text-[var(--muted-foreground)]" />
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t(
              'No linked folders yet. Click "Link folder" to keep a local source in sync.',
            )}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {folders.map((folder) => (
            <FolderCard
              key={folder.id}
              folder={folder}
              busy={syncingId === folder.id || removingId === folder.id}
              syncing={syncingId === folder.id}
              removing={removingId === folder.id}
              readOnly={readOnly}
              onSync={() => void handleSync(folder)}
              onUnlink={() => void handleUnlink(folder.id)}
            />
          ))}
        </div>
      )}

      {task && (task.executing || task.error) && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
            {task.executing && (
              <Loader2 className="h-3 w-3 animate-spin text-[var(--muted-foreground)]" />
            )}
            {task.executing ? task.label : task.error}
          </div>
          {task.executing && percent !== null && (
            <div className="mt-2 h-1 rounded-full bg-[var(--muted)]">
              <div
                className="h-1 rounded-full bg-[var(--primary)] transition-[width]"
                style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FolderCard({
  folder,
  busy,
  syncing,
  removing,
  readOnly,
  onSync,
  onUnlink,
}: {
  folder: LinkedFolderInfo;
  busy: boolean;
  syncing: boolean;
  removing: boolean;
  readOnly: boolean;
  onSync: () => void;
  onUnlink: () => void;
}) {
  const { t } = useTranslation();
  const lastSync = formatKnowledgeTimestamp(folder.last_sync ?? undefined);

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <FolderSync className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
          <span
            className="truncate font-mono text-[12.5px] text-[var(--foreground)]"
            title={folder.path}
          >
            {folder.path}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--muted-foreground)]">
          <span>
            {t("Files")}: {folder.file_count}
          </span>
          <span>
            {t("Added")}: {formatKnowledgeTimestamp(folder.added_at)}
          </span>
          {lastSync && (
            <span>
              {t("Last synced")}: {lastSync}
            </span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={onSync}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
        >
          {syncing ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCw className="h-3 w-3" />
          )}
          {syncing ? t("Syncing…") : t("Sync now")}
        </button>
        {!readOnly && (
          <button
            type="button"
            onClick={onUnlink}
            disabled={busy}
            title={t("Unlink folder")}
            aria-label={t("Unlink folder")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-600 disabled:opacity-50"
          >
            {removing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}
