"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Clock3,
  Download,
  Image as ImageIcon,
  Link2Off,
  Loader2,
  RefreshCcw,
  Trash2,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import Tooltip from "@/components/common/Tooltip";
import {
  cancelMediaJob,
  deleteMediaArtifact,
  fetchMediaArtifact,
  fetchMediaJob,
  retryMediaJob,
} from "@/lib/media-api";
import {
  canCancelJob,
  canRetryJob,
  formatJobElapsed,
  jobErrorDisplay,
  jobStatusMeta,
  sanitizeMediaText,
  type JobStatusTone,
} from "@/lib/media-job-card";
import type { MediaArtifact, MediaJobCard } from "@/lib/media-types";

// Restrained r9 color blocks that read on both light and dark themes.
const TONE_CLASS: Record<JobStatusTone, { block: string; badge: string }> = {
  blue: {
    block: "border-sky-500/70 bg-sky-500/10",
    badge: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  },
  amber: {
    block: "border-amber-500/70 bg-amber-500/10",
    badge: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  green: {
    block: "border-emerald-500/70 bg-emerald-500/10",
    badge: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  },
  coral: {
    block: "border-rose-500/70 bg-rose-500/10",
    badge: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  },
};

const STATUS_ICON: Record<string, LucideIcon> = {
  Clock3,
  Loader2,
  ImageIcon,
  AlertTriangle,
  XCircle,
};

/** Poll cadence: active jobs poll every 2s; cancelled-unconfirmed (remote may
 *  still run) polls every 8s; terminal jobs never poll again. */
function pollIntervalFor(job: MediaJobCard): number | null {
  if (job.status === "cancelled_unconfirmed") return 8000;
  if (job.status === "queued" || job.status === "running" || job.status === "polling") {
    return 2000;
  }
  if (job.status === "validating" || job.status === "saving" || job.status === "cancel_requested") {
    return 4000;
  }
  return null;
}

function isActiveStatus(status: MediaJobCard["status"]): boolean {
  return status === "queued" || status === "running" || status === "polling" ||
    status === "validating" || status === "saving" || status === "cancel_requested";
}

function ConfirmRemoveDialog({
  artifact,
  onConfirm,
  onClose,
}: {
  artifact: MediaArtifact;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const refs = artifact.reference_count;
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
          {t("media.remove_everywhere_confirm_body", { count: refs })}
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

/**
 * A persistent image-generation job card (§13.4). Renders immediately with a
 * stable dimension for queued/running/polling + elapsed time, polls the
 * durable job state, and shows every approved terminal/intermediate state. On
 * success it loads the persisted artifact and shows the real preview, download
 * and a compact icon menu (tooltips).
 */
export function ImageJobCard({
  job: initialJob,
  onChanged,
  onError,
  className,
}: {
  job: MediaJobCard;
  onChanged?: (job: MediaJobCard) => void;
  onError?: (message: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const [job, setJob] = useState(initialJob);
  const [now, setNow] = useState(() => Date.now());
  const [artifact, setArtifact] = useState<MediaArtifact | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState<"cancel" | "retry" | "retryProfile" | "remove" | null>(null);
  const [profileFormOpen, setProfileFormOpen] = useState(false);
  const [retryProfile, setRetryProfile] = useState(initialJob.profile);
  const [retryModel, setRetryModel] = useState(initialJob.model);
  const [retryProtocol, setRetryProtocol] = useState(initialJob.protocol);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const status = job.status;
  const meta = jobStatusMeta(status);
  const StatusIcon = STATUS_ICON[meta.icon] ?? Loader2;
  const tone = TONE_CLASS[meta.tone];
  const active = isActiveStatus(status);

  // Keep the card in sync if the parent hands us a refreshed job.
  useEffect(() => {
    setJob(initialJob);
  }, [initialJob]);

  // Local elapsed ticker for active jobs.
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);

  const elapsedSeconds = useMemo(() => {
    if (job.started_at) {
      return active ? (now - job.started_at * 1000) / 1000 : job.elapsed_seconds;
    }
    return job.elapsed_seconds;
  }, [job.started_at, job.elapsed_seconds, active, now]);

  // A succeeded job loads its persisted artifact (on refresh and on poll).
  useEffect(() => {
    if (status !== "succeeded") return;
    void loadArtifact(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, status]);

  // Poll the durable job state.
  useEffect(() => {
    const interval = pollIntervalFor(job);
    if (interval === null) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const fresh = await fetchMediaJob(job.id);
        if (cancelled) return;
        setJob(fresh);
        onChanged?.(fresh);
      } catch {
        // Transient poll failure: keep the last-known state; the next tick or
        // a manual refresh recovers.
      }
    };
    const id = window.setInterval(tick, interval);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, status]);

  const loadArtifact = useCallback(async (fresh: MediaJobCard) => {
    if (!fresh.artifact_ids?.length) return;
    try {
      const view = await fetchMediaArtifact(fresh.artifact_ids[0]);
      setArtifact(view);
    } catch {
      // Artifact may be mid-GC or already removed; the card stays stable.
    }
  }, []);

  const handleCancel = useCallback(async () => {
    setBusy("cancel");
    try {
      const fresh = await cancelMediaJob(job.id, job.status_version);
      if (!mountedRef.current) return;
      setJob(fresh);
      onChanged?.(fresh);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }, [job.id, job.status_version, onChanged, onError]);

  const handleRetry = useCallback(
    async (withProfile: boolean) => {
      setBusy(withProfile ? "retryProfile" : "retry");
      try {
        const fresh = await retryMediaJob(job.id, {
          expected_status_version: job.status_version,
          profile: withProfile ? retryProfile.trim() : undefined,
          model: withProfile ? retryModel.trim() : undefined,
          protocol: withProfile ? retryProtocol.trim() : undefined,
        });
        if (!mountedRef.current) return;
        setJob(fresh);
        setProfileFormOpen(false);
        onChanged?.(fresh);
      } catch (err) {
        onError?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (mountedRef.current) setBusy(null);
      }
    },
    [job.id, job.status_version, retryProfile, retryModel, retryProtocol, onChanged, onError],
  );

  const handleDetachFromChat = useCallback(async () => {
    if (!artifact || !job.session_id) return;
    setBusy("remove");
    try {
      const updated = await deleteMediaArtifact(artifact.id, {
        mode: "detach_current",
        owner_type: "session",
        owner_id: job.session_id,
      });
      if (!mountedRef.current) return;
      setArtifact(updated);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }, [artifact, job.session_id, onError]);

  const handleRemoveEverywhere = useCallback(async () => {
    if (!artifact) return;
    setBusy("remove");
    setConfirmRemove(false);
    try {
      const updated = await deleteMediaArtifact(artifact.id, {
        mode: "remove_everywhere",
        confirmed: true,
      });
      if (!mountedRef.current) return;
      setArtifact(updated);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }, [artifact, onError]);

  const errorText = jobErrorDisplay(job);
  const identity = [job.profile, job.protocol, job.model].filter(Boolean).join(" · ") || t("media.unknown_identity");

  return (
    <div
      data-media-job-card=""
      data-status={status}
      className={`max-w-[min(560px,100%)] rounded-xl border-2 border-l-4 p-3 shadow-sm ${tone.block} ${className ?? ""}`}
    >
      {/* Header: status block + elapsed — stable row. */}
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-semibold ${tone.badge}`}
          >
            <StatusIcon className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{t(meta.labelKey)}</span>
          </span>
          <span className="w-14 shrink-0 text-right text-[11px] tabular-nums text-[var(--muted-foreground)]">
            {formatJobElapsed(elapsedSeconds)}
          </span>
        </div>
        <span className="truncate text-[10.5px] uppercase tracking-wide text-[var(--muted-foreground)]">
          {job.operation}
        </span>
      </div>

      {/* Prompt — clamped so dynamic content never resizes the chat layout. */}
      <p className="mt-2 line-clamp-2 text-[13px] font-medium text-[var(--foreground)]">
        {sanitizeMediaText(job.prompt)}
      </p>

      {/* Identity line. */}
      <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]" title={identity}>
        {identity}
      </p>

      {/* Sanitized error — single line, clamped. */}
      {errorText ? (
        <p className="mt-1 truncate text-[11.5px] text-rose-600 dark:text-rose-300" title={errorText}>
          {errorText}
        </p>
      ) : null}

      {/* Succeeded artifact preview + download + compact menu. */}
      {status === "succeeded" && artifact ? (
        <div className="mt-2.5 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={artifact.preview_url ?? ""}
            alt={artifact.original_prompt || t("media.generated_image")}
            loading="lazy"
            className="block max-h-[280px] w-full bg-[var(--background)] object-contain"
          />
          <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] px-2.5 py-1.5">
            <span className="min-w-0 truncate text-[11px] text-[var(--muted-foreground)]">
              {artifact.width}×{artifact.height} · {job.profile}
            </span>
            <div className="flex shrink-0 items-center gap-0.5">
              <Tooltip label={t("media.download")}>
                <a
                  href={artifact.download_url ?? ""}
                  download
                  aria-label={t("media.download")}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  <Download className="h-4 w-4" />
                </a>
              </Tooltip>
              <Tooltip label={t("media.detach_from_chat")}>
                <button
                  type="button"
                  disabled={busy === "remove"}
                  onClick={() => void handleDetachFromChat()}
                  aria-label={t("media.detach_from_chat")}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
                >
                  <Link2Off className="h-4 w-4" />
                </button>
              </Tooltip>
              <Tooltip label={t("media.remove_everywhere")}>
                <button
                  type="button"
                  disabled={busy === "remove"}
                  onClick={() => setConfirmRemove(true)}
                  aria-label={t("media.remove_everywhere")}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--destructive)] disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </Tooltip>
            </div>
          </div>
        </div>
      ) : status === "succeeded" ? (
        <div className="mt-2.5 flex h-16 items-center justify-center rounded-lg border border-dashed border-[var(--border)] text-[11px] text-[var(--muted-foreground)]">
          <ImageIcon className="mr-2 h-4 w-4" aria-hidden="true" />
          {t("media.loading_artifact")}
        </div>
      ) : null}

      {/* Actions. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {canCancelJob(status) ? (
          <button
            type="button"
            disabled={busy === "cancel"}
            onClick={() => void handleCancel()}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[11.5px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            {t("media.cancel")}
          </button>
        ) : null}

        {canRetryJob(status) ? (
          <>
            <button
              type="button"
              disabled={busy === "retry"}
              onClick={() => void handleRetry(false)}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[11.5px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
            >
              <RefreshCcw className="h-3.5 w-3.5" aria-hidden="true" />
              {t("media.retry")}
            </button>
            <button
              type="button"
              onClick={() => setProfileFormOpen((open) => !open)}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[11.5px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {t("media.retry_with_profile")}
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform ${profileFormOpen ? "rotate-180" : ""}`}
                aria-hidden="true"
              />
            </button>
          </>
        ) : null}
      </div>

      {/* Profile-change retry form — explicit new lineage with visible identity. */}
      {profileFormOpen && canRetryJob(status) ? (
        <div className="mt-2 grid grid-cols-3 gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2">
          <label className="col-span-1 text-[10px] font-medium text-[var(--muted-foreground)]">
            {t("media.profile")}
            <input
              value={retryProfile}
              onChange={(e) => setRetryProfile(e.target.value)}
              className="mt-0.5 w-full rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-1 text-[11px] text-[var(--foreground)]"
            />
          </label>
          <label className="col-span-1 text-[10px] font-medium text-[var(--muted-foreground)]">
            {t("media.model")}
            <input
              value={retryModel}
              onChange={(e) => setRetryModel(e.target.value)}
              className="mt-0.5 w-full rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-1 text-[11px] text-[var(--foreground)]"
            />
          </label>
          <label className="col-span-1 text-[10px] font-medium text-[var(--muted-foreground)]">
            {t("media.protocol")}
            <input
              value={retryProtocol}
              onChange={(e) => setRetryProtocol(e.target.value)}
              className="mt-0.5 w-full rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-1 text-[11px] text-[var(--foreground)]"
            />
          </label>
          <button
            type="button"
            disabled={busy === "retryProfile"}
            onClick={() => void handleRetry(true)}
            className="col-span-3 mt-1 inline-flex items-center justify-center gap-1 rounded-md border border-[var(--border)] bg-[var(--muted)] px-2 py-1 text-[11.5px] font-medium text-[var(--foreground)] hover:bg-[var(--border)] disabled:opacity-50"
          >
            <RefreshCcw className="h-3.5 w-3.5" aria-hidden="true" />
            {t("media.create_retry_lineage")}
          </button>
        </div>
      ) : null}

      {/* cancelled_unconfirmed needs an explicit non-color notice. */}
      {status === "cancelled_unconfirmed" ? (
        <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
          {t("media.cancelled_unconfirmed_hint")}
        </p>
      ) : null}

      {confirmRemove && artifact ? (
        <ConfirmRemoveDialog
          artifact={artifact}
          onClose={() => setConfirmRemove(false)}
          onConfirm={() => void handleRemoveEverywhere()}
        />
      ) : null}
    </div>
  );
}

export default ImageJobCard;
