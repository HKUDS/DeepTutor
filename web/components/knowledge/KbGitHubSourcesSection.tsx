"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Github, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  addGitHubSource,
  listGitHubSources,
  removeGitHubSource,
  syncGitHubSources,
  type GitHubSource,
  type GitHubSyncResult,
} from "@/features/knowledge/api/sources";
import { formatKnowledgeTimestamp } from "@/lib/knowledge-helpers";

interface KbGitHubSourcesSectionProps {
  kbName: string;
}

export default function KbGitHubSourcesSection({
  kbName,
}: KbGitHubSourcesSectionProps) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<GitHubSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Inline form state
  const [repoInput, setRepoInput] = useState("");
  const [branchInput, setBranchInput] = useState("main");
  const [pathInput, setPathInput] = useState("");
  const [globInput, setGlobInput] = useState("*.md");
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await listGitHubSources(kbName);
      setSources(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [kbName]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleAdd = async () => {
    const repo = repoInput.trim();
    if (!repo) return;
    setSubmitting(true);
    setError(null);
    try {
      await addGitHubSource(kbName, {
        repo,
        branch: branchInput.trim() || "main",
        path: pathInput.trim(),
        glob: globInput.trim() || "*.md",
      });
      setRepoInput("");
      setBranchInput("main");
      setPathInput("");
      setGlobInput("*.md");
      setShowForm(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (sourceId: string) => {
    setError(null);
    try {
      await removeGitHubSource(kbName, sourceId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const results: GitHubSyncResult[] = await syncGitHubSources(kbName);
      // Briefly surface per-source results
      const failed = results.filter((r) => !r.ok);
      if (failed.length > 0) {
        setError(
          failed
            .map((r) => `${r.repo}: ${r.error ?? "unknown error"}`)
            .join("\n"),
        );
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {t("GitHub Sources")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t(
              "Track a GitHub repo's Markdown docs. DeepTutor auto-syncs daily; you can also trigger a sync manually.",
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleSync()}
            disabled={syncing || sources.length === 0}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
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
            onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            <Plus className="h-3 w-3" />
            {t("Add source")}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50/60 p-2.5 text-[11.5px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Add form */}
      {showForm && (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label={t("Repo (owner/name)")}>
              <input
                type="text"
                value={repoInput}
                onChange={(e) => setRepoInput(e.target.value)}
                placeholder={t("e.g. HKUDS/DeepTutor")}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
              />
            </FormField>
            <FormField label={t("Branch")}>
              <input
                type="text"
                value={branchInput}
                onChange={(e) => setBranchInput(e.target.value)}
                placeholder={t("main")}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
              />
            </FormField>
            <FormField
              label={t("Path prefix")}
              help={t("e.g. docs/ — leave empty for root")}
            >
              <input
                type="text"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                placeholder={t("docs/")}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
              />
            </FormField>
            <FormField label={t("Glob pattern")}>
              <input
                type="text"
                value={globInput}
                onChange={(e) => setGlobInput(e.target.value)}
                placeholder={t("*.md")}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
              />
            </FormField>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleAdd()}
              disabled={submitting || !repoInput.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
              {t("Add")}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              {t("Cancel")}
            </button>
          </div>
        </div>
      )}

      {/* Source list */}
      {sources.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] py-8 text-center">
          <Github className="mx-auto mb-2 h-6 w-6 text-[var(--muted-foreground)]" />
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t('No GitHub sources yet. Click "Add source" to track a repo.')}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sources.map((src) => (
            <SourceCard
              key={src.id}
              source={src}
              onRemove={() => void handleRemove(src.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SourceCard({
  source,
  onRemove,
}: {
  source: GitHubSource;
  onRemove: () => void;
}) {
  const { t } = useTranslation();

  const statusColor =
    source.last_sync_status === "success"
      ? "text-emerald-600 dark:text-emerald-400"
      : source.last_sync_status === "error"
        ? "text-red-600 dark:text-red-400"
        : "text-[var(--muted-foreground)]";

  const lastSync = formatKnowledgeTimestamp(source.last_synced_at);

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Github className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
          <span className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
            {source.repo}
          </span>
          <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]">
            @{source.branch}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--muted-foreground)]">
          <span>
            {t("Path")}: <code className="font-mono">{source.path || "/"}</code>
          </span>
          <span>
            {t("Glob")}: <code className="font-mono">{source.glob}</code>
          </span>
          <span className={statusColor}>
            {t("Status")}: {source.last_sync_status}
          </span>
          {source.files_synced > 0 && (
            <span>
              {t("Files")}: {source.files_synced}
            </span>
          )}
          {lastSync && (
            <span>
              {t("Synced")}: {lastSync}
            </span>
          )}
        </div>
        {source.last_sync_error && (
          <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">
            {source.last_sync_error}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={onRemove}
        title={t("Remove source")}
        className="shrink-0 rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-600"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function FormField({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-[var(--muted-foreground)]">
        {label}
      </span>
      {children}
      {help && (
        <span className="mt-0.5 block text-[10px] text-[var(--muted-foreground)]">
          {help}
        </span>
      )}
    </label>
  );
}
