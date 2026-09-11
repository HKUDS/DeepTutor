"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Ban,
  Globe,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import {
  cancelWebSourceSync,
  addWebSource,
  listWebSources,
  removeWebSource,
  retryWebSourceSync,
  syncWebSources,
  updateWebSourceSchedule,
  listWebSourceSyncJobs,
  type WebSource,
  type WebSourceSyncJob,
} from "@/features/knowledge/api/sources";
import { formatKnowledgeTimestamp } from "@/lib/knowledge-helpers";

interface KbWebSourcesSectionProps {
  kbName: string;
}

export default function KbWebSourcesSection({
  kbName,
}: KbWebSourcesSectionProps) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<WebSource[]>([]);
  const [jobs, setJobs] = useState<WebSourceSyncJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [urlInput, setUrlInput] = useState("");
  const [maxDepth, setMaxDepth] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [busySource, setBusySource] = useState<string | null>(null);
  const [intervalInputs, setIntervalInputs] = useState<Record<string, number>>(
    {},
  );

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const [nextSources, nextJobs] = await Promise.all([
        listWebSources(kbName, { signal: controller.signal }),
        listWebSourceSyncJobs(kbName, { signal: controller.signal }),
      ]);
      setSources(nextSources);
      setJobs(nextJobs);
      setError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Timed out loading web sources. Click retry.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }, [kbName]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const hasActiveJob = jobs.some(
      (job) => job.state === "running" || job.state === "pending",
    );
    if (!hasActiveJob) return;
    const timer = setInterval(() => void refresh(), 5_000);
    return () => clearInterval(timer);
  }, [jobs, refresh]);

  const handleAdd = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setSubmitting(true);
    setError(null);
    try {
      await addWebSource(kbName, { url, max_depth: maxDepth });
      setUrlInput("");
      setMaxDepth(3);
      setShowForm(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (id: string) => {
    setError(null);
    try {
      await removeWebSource(kbName, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    try {
      await syncWebSources(kbName);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const withSourceAction = async (id: string, action: () => Promise<void>) => {
    setBusySource(id);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusySource(null);
    }
  };

  const handleScheduleChange = (
    source: WebSource,
    autoSyncEnabled: boolean,
    syncIntervalHours: number,
  ) => {
    const interval = Math.min(168, Math.max(1, syncIntervalHours || 24));
    setIntervalInputs((current) => ({ ...current, [source.id]: interval }));
    return withSourceAction(source.id, async () => {
      await updateWebSourceSchedule(kbName, source.id, {
        auto_sync_enabled: autoSyncEnabled,
        sync_interval_hours: interval,
      });
    });
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10">
        {error ? (
          <>
            <p className="text-[12px] text-red-600 dark:text-red-400">
              {error}
            </p>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setLoading(true);
                void refresh();
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
            >
              <RefreshCw className="h-3 w-3" />
              {t("Retry")}
            </button>
          </>
        ) : (
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {t("Web Sources")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t(
              "Crawl a documentation website on demand with bounded depth and page limits.",
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

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50/60 p-2.5 text-[11.5px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
          {error}
        </div>
      )}

      {showForm && (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--muted-foreground)]">
              {t("Documentation URL")}
            </span>
            <input
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder={t("https://docs.deeptutor.info/")}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--muted-foreground)]">
              {t("Max crawl depth")}
            </span>
            <input
              type="number"
              min={1}
              max={5}
              value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value) || 3)}
              className="w-24 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleAdd()}
              disabled={submitting || !urlInput.trim()}
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

      {sources.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] py-8 text-center">
          <Globe className="mx-auto mb-2 h-6 w-6 text-[var(--muted-foreground)]" />
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t('No web sources yet. Click "Add source" to crawl a doc site.')}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sources.map((src) => (
            <WebSourceCard
              key={src.id}
              source={src}
              job={jobs.find((job) => job.source_id === src.id)}
              busy={busySource === src.id}
              intervalValue={intervalInputs[src.id] ?? src.sync_interval_hours}
              onIntervalInput={(hours) =>
                setIntervalInputs((current) => ({
                  ...current,
                  [src.id]: hours,
                }))
              }
              onScheduleChange={(autoSync, hours) =>
                void handleScheduleChange(src, autoSync, hours)
              }
              onCancel={() =>
                void withSourceAction(src.id, () =>
                  cancelWebSourceSync(kbName, src.id),
                )
              }
              onRetry={() =>
                void withSourceAction(src.id, () =>
                  retryWebSourceSync(kbName, src.id),
                )
              }
              onRemove={() => void handleRemove(src.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function WebSourceCard({
  source,
  job,
  busy,
  intervalValue,
  onIntervalInput,
  onScheduleChange,
  onCancel,
  onRetry,
  onRemove,
}: {
  source: WebSource;
  job?: WebSourceSyncJob;
  busy: boolean;
  intervalValue: number;
  onIntervalInput: (hours: number) => void;
  onScheduleChange: (enabled: boolean, interval: number) => void;
  onCancel: () => void;
  onRetry: () => void;
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
  const jobColor =
    job?.state === "running"
      ? "text-blue-600 dark:text-blue-400"
      : job?.state === "error" || job?.state === "interrupted"
        ? "text-red-600 dark:text-red-400"
        : job?.state === "cancelled"
          ? "text-amber-600 dark:text-amber-400"
          : "text-[var(--muted-foreground)]";
  const nextRun =
    job?.state === "pending" && job.next_run_at
      ? new Date(job.next_run_at).toLocaleString()
      : "";

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Globe className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
          <span className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
            {source.url}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--muted-foreground)]">
          <span>
            {t("Depth")}: {source.max_depth}
          </span>
          <span className={statusColor}>
            {t("Status")}: {source.last_sync_status}
          </span>
          {source.page_count > 0 && (
            <span>
              {t("Pages")}: {source.page_count}
            </span>
          )}
          {lastSync && (
            <span>
              {t("Synced")}: {lastSync}
            </span>
          )}
          {job && (
            <span className={jobColor}>
              {t("Schedule")}: {t(job.state === "interrupted" ? "Interrupted" : job.state)}
            </span>
          )}
          {nextRun && <span>{t("Next run")}: {nextRun}</span>}
          {job?.cancel_requested && <span>{t("Cancelling…")}</span>}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-1.5 text-[11px]">
            <input
              type="checkbox"
              checked={source.auto_sync_enabled}
              disabled={busy}
              onChange={(event) =>
                onScheduleChange(event.target.checked, intervalValue)
              }
              aria-label={t("Automatic sync")}
            />
            {t("Automatic sync")}
          </label>
          <label className="inline-flex items-center gap-1.5 text-[11px]">
            <span>{t("Interval hours")}</span>
            <input
              type="number"
              min={1}
              max={168}
              value={intervalValue}
              disabled={busy || !source.auto_sync_enabled}
              onChange={(event) => onIntervalInput(Number(event.target.value) || 24)}
              onBlur={(event) =>
                onScheduleChange(
                  source.auto_sync_enabled,
                  Number(event.target.value) || 24,
                )
              }
              className="w-16 rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 py-1 text-[11px] text-[var(--foreground)] outline-none focus:border-[var(--primary)] disabled:opacity-50"
              aria-label={t("Interval hours")}
            />
          </label>
        </div>
        {source.last_sync_error && (
          <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">
            {source.last_sync_error}
          </p>
        )}
        {job?.error && (
          <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">
            {job.error}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {job?.state === "running" || job?.state === "pending" ? (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            title={t("Cancel sync")}
            aria-label={t("Cancel sync")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-600 disabled:opacity-50"
          >
            <Ban className="h-3.5 w-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onRetry}
            disabled={busy || !source.enabled || !source.auto_sync_enabled}
            title={t("Retry sync")}
            aria-label={t("Retry sync")}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          type="button"
          onClick={onRemove}
          title={t("Remove source")}
          aria-label={t("Remove source")}
          className="shrink-0 rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-600"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
