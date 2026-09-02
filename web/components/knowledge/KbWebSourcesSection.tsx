"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Globe, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  addWebSource,
  listWebSources,
  removeWebSource,
  syncWebSources,
  type WebSource,
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
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [urlInput, setUrlInput] = useState("");
  const [maxDepth, setMaxDepth] = useState(3);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      setSources(await listWebSources(kbName, { signal: controller.signal }));
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
  onRemove,
}: {
  source: WebSource;
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
