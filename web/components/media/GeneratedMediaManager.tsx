"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Download,
  Link2,
  RefreshCcw,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import Tooltip from "@/components/common/Tooltip";
import {
  deleteMediaArtifact,
  fetchMediaArtifacts,
  runMediaGc,
} from "@/lib/media-api";
import {
  formatBytes,
  hasReclaimableQuota,
  sortMediaArtifacts,
  type ArtifactSortKey,
} from "@/lib/media-job-card";
import type { MediaArtifact, MediaQuota } from "@/lib/media-types";

const SORT_OPTIONS: Array<{ key: ArtifactSortKey; labelKey: string }> = [
  { key: "newest", labelKey: "media.sort_newest" },
  { key: "oldest", labelKey: "media.sort_oldest" },
  { key: "largest", labelKey: "media.sort_largest" },
  { key: "refs", labelKey: "media.sort_refs" },
];

function quotaPercent(quota: MediaQuota): number {
  if (!quota.limit_bytes) return 0;
  return Math.min(100, Math.round((quota.used_bytes / quota.limit_bytes) * 100));
}

function ConfirmDeleteDialog({
  artifact,
  onConfirm,
  onClose,
}: {
  artifact: MediaArtifact;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={t("media.remove_everywhere_confirm_title")}
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-start justify-between gap-3">
          <h3 className="text-[14px] font-semibold text-[var(--foreground)]">
            {t("media.remove_everywhere_confirm_title")}
          </h3>
          <button
            type="button"
            aria-label={t("media.close")}
            onClick={onClose}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t("media.remove_everywhere_confirm_body", { count: artifact.reference_count })}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)]"
          >
            {t("media.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg bg-[var(--destructive)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--destructive-foreground)] hover:opacity-90"
          >
            {t("media.delete_everywhere")}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDateTime(seconds: number): string {
  if (!seconds) return "—";
  return new Date(seconds * 1000).toLocaleString();
}

/**
 * Generated-media management (§12.3) shown under the image settings surface.
 * Lists the current user's artifacts sortable by size/time/reference count,
 * shows used/limit/reclaimable quota, and provides immediate eligible cleanup.
 */
export function GeneratedMediaManager({
  onError,
}: {
  onError?: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [artifacts, setArtifacts] = useState<MediaArtifact[]>([]);
  const [quota, setQuota] = useState<MediaQuota | null>(null);
  const [sortKey, setSortKey] = useState<ArtifactSortKey>("newest");
  const [loading, setLoading] = useState(true);
  const [gcRunning, setGcRunning] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { artifacts: list, quota: q } = await fetchMediaArtifacts();
      setArtifacts(list);
      setQuota(q);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sorted = useMemo(
    () => sortMediaArtifacts(artifacts, sortKey),
    [artifacts, sortKey],
  );

  const handleGc = useCallback(async () => {
    setGcRunning(true);
    try {
      await runMediaGc();
      await refresh();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setGcRunning(false);
    }
  }, [refresh, onError]);

  const handleDelete = useCallback(
    async (artifact: MediaArtifact) => {
      setDeletingId(artifact.id);
      setConfirmId(null);
      try {
        const updated = await deleteMediaArtifact(artifact.id, {
          mode: "remove_everywhere",
          confirmed: true,
        });
        setArtifacts((list) =>
          list.map((item) => (item.id === updated.id ? updated : item)),
        );
        await refresh();
      } catch (err) {
        onError?.(err instanceof Error ? err.message : String(err));
      } finally {
        setDeletingId(null);
      }
    },
    [refresh, onError],
  );

  if (loading) {
    return (
      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-[12.5px] text-[var(--muted-foreground)]">
        {t("media.loading_media")}
      </div>
    );
  }

  const confirmArtifact = artifacts.find((a) => a.id === confirmId) ?? null;

  return (
    <div className="mt-6" data-media-manager="">
      <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
        {t("media.generated_media_title")}
      </h2>

      {/* Quota summary + eligible cleanup. */}
      {quota ? (
        <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--muted-foreground)]">
              <span>
                {t("media.quota_used", {
                  used: formatBytes(quota.used_bytes),
                  limit: formatBytes(quota.limit_bytes),
                })}
              </span>
              <span>{t("media.quota_files", { count: quota.file_count })}</span>
              {quota.reclaimable_bytes > 0 ? (
                <span className="font-medium text-emerald-700 dark:text-emerald-300">
                  {t("media.quota_reclaimable", {
                    amount: formatBytes(quota.reclaimable_bytes),
                  })}
                </span>
              ) : null}
            </div>
            <button
              type="button"
              disabled={!hasReclaimableQuota(quota) || gcRunning}
              onClick={() => void handleGc()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
            >
              <RefreshCcw className={`h-3.5 w-3.5 ${gcRunning ? "animate-spin" : ""}`} aria-hidden="true" />
              {t("media.cleanup_reclaimable")}
            </button>
          </div>
          <div
            role="meter"
            aria-label={t("media.quota_meter")}
            aria-valuenow={quota.used_bytes}
            aria-valuemin={0}
            aria-valuemax={quota.limit_bytes}
            className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-[var(--muted)]"
          >
            <div
              className={`h-full rounded-full ${quotaPercent(quota) > 90 ? "bg-[var(--destructive)]" : "bg-[var(--primary)]"}`}
              style={{ width: `${quotaPercent(quota)}%` }}
            />
          </div>
        </div>
      ) : null}

      {/* Sort control. */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="text-[11.5px] font-medium text-[var(--muted-foreground)]">
          {t("media.sort_by")}
        </span>
        {SORT_OPTIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setSortKey(option.key)}
            aria-pressed={sortKey === option.key}
            className={`rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors ${
              sortKey === option.key
                ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {t(option.labelKey)}
          </button>
        ))}
      </div>

      {/* Artifact list — responsive grid that never overlaps. */}
      {sorted.length === 0 ? (
        <div className="mt-3 rounded-xl border border-dashed border-[var(--border)] p-6 text-center text-[12.5px] text-[var(--muted-foreground)]">
          {t("media.no_generated_media")}
        </div>
      ) : (
        <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {sorted.map((artifact) => (
            <li
              key={artifact.id}
              data-artifact-id={artifact.id}
              className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={artifact.preview_url ?? ""}
                alt={artifact.original_prompt || t("media.generated_image")}
                loading="lazy"
                className="block h-36 w-full bg-[var(--background)] object-contain"
              />
              <div className="flex min-w-0 flex-1 flex-col gap-1 p-2.5">
                <p className="line-clamp-1 text-[12px] font-medium text-[var(--foreground)]">
                  {artifact.original_prompt || t("media.generated_image")}
                </p>
                <p className="text-[11px] text-[var(--muted-foreground)]">
                  {artifact.width}×{artifact.height} · {formatBytes(artifact.size_bytes)}
                </p>
                <p className="text-[11px] text-[var(--muted-foreground)]">
                  {t("media.created_at", { time: formatDateTime(artifact.created_at) })}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ${
                      artifact.reference_count > 0
                        ? "bg-sky-500/15 text-sky-700 dark:text-sky-300"
                        : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    <Link2 className="h-3 w-3" aria-hidden="true" />
                    {artifact.reference_count}
                  </span>
                  {artifact.is_gc_candidate ? (
                    <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-300">
                      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                      {t("media.gc_candidate")}
                    </span>
                  ) : null}
                </div>
                <div className="mt-auto flex items-center justify-end gap-0.5 pt-1.5">
                  {artifact.download_url ? (
                    <Tooltip label={t("media.download")}>
                      <a
                        href={artifact.download_url}
                        download
                        aria-label={t("media.download")}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                      >
                        <Download className="h-4 w-4" />
                      </a>
                    </Tooltip>
                  ) : null}
                  <Tooltip label={t("media.remove_everywhere")}>
                    <button
                      type="button"
                      disabled={deletingId === artifact.id}
                      onClick={() => setConfirmId(artifact.id)}
                      aria-label={t("media.remove_everywhere")}
                      className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--destructive)] disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </Tooltip>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {confirmArtifact ? (
        <ConfirmDeleteDialog
          artifact={confirmArtifact}
          onClose={() => setConfirmId(null)}
          onConfirm={() => void handleDelete(confirmArtifact)}
        />
      ) : null}
    </div>
  );
}

export default GeneratedMediaManager;
