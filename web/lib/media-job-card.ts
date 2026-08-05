// Pure media job-card + artifact-management logic (MED-03).
//
// Everything in this module is framework-free so the node contract tests can
// assert every job state, retry/cancel permission, sanitization and reference/
// quota action without a DOM.  The React components render these decisions.

import type {
  ImageJobStatus,
  MediaArtifact,
  MediaJobCard,
} from "@/lib/media-types";
import type { StreamEvent } from "@/lib/unified-ws";

// ── job lifecycle groups (r9 color blocks) ───────────────────────────────────

export type JobStatusTone = "blue" | "amber" | "green" | "coral";

export interface JobStatusMeta {
  tone: JobStatusTone;
  /** i18n key for the non-color status label (accessibility). */
  labelKey: string;
  /** Lucide icon name used for the status glyph. */
  icon: "Clock3" | "Loader2" | "Image" | "AlertTriangle" | "XCircle";
  active: boolean;
  terminal: boolean;
}

const JOB_STATUS_META: Record<ImageJobStatus, JobStatusMeta> = {
  queued: { tone: "blue", labelKey: "media.status.queued", icon: "Clock3", active: true, terminal: false },
  running: { tone: "amber", labelKey: "media.status.running", icon: "Loader2", active: true, terminal: false },
  polling: { tone: "amber", labelKey: "media.status.polling", icon: "Loader2", active: true, terminal: false },
  validating: { tone: "amber", labelKey: "media.status.validating", icon: "Loader2", active: true, terminal: false },
  saving: { tone: "amber", labelKey: "media.status.saving", icon: "Loader2", active: true, terminal: false },
  succeeded: { tone: "green", labelKey: "media.status.succeeded", icon: "Image", active: false, terminal: true },
  failed: { tone: "coral", labelKey: "media.status.failed", icon: "AlertTriangle", active: false, terminal: true },
  timed_out: { tone: "coral", labelKey: "media.status.timed_out", icon: "AlertTriangle", active: false, terminal: true },
  unknown: { tone: "coral", labelKey: "media.status.unknown", icon: "AlertTriangle", active: false, terminal: true },
  cancel_requested: { tone: "coral", labelKey: "media.status.cancel_requested", icon: "XCircle", active: true, terminal: false },
  cancelled: { tone: "coral", labelKey: "media.status.cancelled", icon: "XCircle", active: false, terminal: true },
  cancelled_unconfirmed: { tone: "coral", labelKey: "media.status.cancelled_unconfirmed", icon: "XCircle", active: false, terminal: true },
};

export function jobStatusMeta(status: ImageJobStatus): JobStatusMeta {
  return JOB_STATUS_META[status] ?? JOB_STATUS_META.unknown;
}

export function isActiveJob(status: ImageJobStatus): boolean {
  return jobStatusMeta(status).active;
}

export function isTerminalJob(status: ImageJobStatus): boolean {
  return jobStatusMeta(status).terminal;
}

/** Cancel is only offered for states the backend accepts (§11.6). */
export function canCancelJob(status: ImageJobStatus): boolean {
  return status === "queued" || status === "running" || status === "polling";
}

/** Retry (new lineage) is only offered for terminal failure/cancel states. */
export function canRetryJob(status: ImageJobStatus): boolean {
  return (
    status === "failed" ||
    status === "timed_out" ||
    status === "unknown" ||
    status === "cancelled" ||
    status === "cancelled_unconfirmed"
  );
}

// ── elapsed time ─────────────────────────────────────────────────────────────

/** "05:12" for <1h, "1h 02m" above; stable width for the card layout. */
export function formatJobElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// ── client-side sanitization (defense in depth) ──────────────────────────────

const CLIENT_SECRET_PATTERNS: RegExp[] = [
  /sk-[A-Za-z0-9_\-]{6,}/g,
  /(authorization\s*[:=]\s*)(?:[A-Za-z0-9._~+/=\-]+\s+)?[A-Za-z0-9._~+/=\-]+/gi,
  /data:[^,]*;base64,/gi,
];

/**
 * Redact credential-looking text before it reaches the DOM.  The backend
 * already sanitizes; this is defense in depth so a legacy/streamed value can
 * never leak a key or a base64 payload into a card.
 */
export function sanitizeMediaText(value: string): string {
  let text = (value ?? "").trim();
  for (const pattern of CLIENT_SECRET_PATTERNS) {
    text = text.replace(pattern, (match, _g1, offset) =>
      offset === 0 && /authorization/i.test(match) ? match : "***",
    );
  }
  // Long contiguous base64 tokens (>= 64 chars) are payloads, not prose.
  if (/[A-Za-z0-9+/=]{64,}/.test(text)) {
    return "[redacted]";
  }
  return text.slice(0, 300);
}

export function jobErrorDisplay(job: MediaJobCard): string {
  if (!job.sanitized_error && !job.error_code) return "";
  if (job.sanitized_error) return sanitizeMediaText(job.sanitized_error);
  return job.error_code;
}

// ── chat message integration (additive hook) ─────────────────────────────────

/** A reference to an image job carried by a message attachment/event. */
export interface MediaJobRef {
  job_id: string;
  id?: string;
}

export function imageJobRefsFromAttachments(
  attachments: Array<{ type?: string; id?: string; [key: string]: unknown }>,
): MediaJobRef[] {
  const out: MediaJobRef[] = [];
  for (const a of attachments ?? []) {
    if (a?.type !== "image_job") continue;
    const jobId = typeof a.job_id === "string" ? (a.job_id as string).trim() : "";
    if (!jobId) continue;
    out.push({ job_id: jobId, id: typeof a.id === "string" ? a.id : undefined });
  }
  return out;
}

/** Image-job refs streamed live in ``tool_result`` events. */
export function imageJobRefsFromEvents(events?: StreamEvent[]): MediaJobRef[] {
  const out: MediaJobRef[] = [];
  for (const ev of events ?? []) {
    if (ev.type !== "tool_result") continue;
    const meta = (ev.metadata ?? {}) as {
      tool_metadata?: {
        image_jobs?: Array<{ job_id?: string }>;
      };
    };
    for (const ref of meta.tool_metadata?.image_jobs ?? []) {
      const jobId = typeof ref?.job_id === "string" ? ref.job_id.trim() : "";
      if (jobId) out.push({ job_id: jobId });
    }
  }
  return out;
}

export function mergeImageJobRefs(
  attachments: Array<{ type?: string; id?: string; [key: string]: unknown }>,
  events?: StreamEvent[],
): MediaJobRef[] {
  const seen = new Set<string>();
  const out: MediaJobRef[] = [];
  for (const ref of [
    ...imageJobRefsFromAttachments(attachments),
    ...imageJobRefsFromEvents(events),
  ]) {
    if (seen.has(ref.job_id)) continue;
    seen.add(ref.job_id);
    out.push(ref);
  }
  return out;
}

// ── artifact management (settings surface) ───────────────────────────────────

export type ArtifactSortKey = "newest" | "oldest" | "largest" | "refs";

export function sortMediaArtifacts(
  artifacts: MediaArtifact[],
  key: ArtifactSortKey,
): MediaArtifact[] {
  const copy = [...artifacts];
  switch (key) {
    case "newest":
      return copy.sort((a, b) => b.created_at - a.created_at);
    case "oldest":
      return copy.sort((a, b) => a.created_at - b.created_at);
    case "largest":
      return copy.sort((a, b) => b.size_bytes - a.size_bytes);
    case "refs":
      return copy.sort((a, b) => b.reference_count - a.reference_count);
    default:
      return copy;
  }
}

export function formatBytes(bytes: number): string {
  const value = Math.max(0, bytes || 0);
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let amount = value;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return index === 0 ? `${amount} ${units[index]}` : `${amount.toFixed(1)} ${units[index]}`;
}

/** Reclaimable bytes are eligible for immediate explicit cleanup (§12.3). */
export function hasReclaimableQuota(quota: { reclaimable_bytes: number }): boolean {
  return quota.reclaimable_bytes > 0;
}
