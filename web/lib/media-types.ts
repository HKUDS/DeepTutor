// Media management types (MED-03). Mirrors the safe browser-facing API view in
// `deeptutor/services/media/views.py` — never a server-side path or a raw
// provider error body.

export type ImageJobStatus =
  | "queued"
  | "running"
  | "polling"
  | "validating"
  | "saving"
  | "succeeded"
  | "failed"
  | "cancel_requested"
  | "cancelled"
  | "cancelled_unconfirmed"
  | "timed_out"
  | "unknown";

export type ImageJobOperation = "generate" | "edit";

export const IMAGE_JOB_ACTIVE_STATUSES: readonly ImageJobStatus[] = [
  "queued",
  "running",
  "polling",
  "validating",
  "saving",
  "cancel_requested",
];

/** Terminal states a user may explicitly retry (new lineage), §11.5. */
export const IMAGE_JOB_RETRYABLE_STATUSES: readonly ImageJobStatus[] = [
  "failed",
  "timed_out",
  "unknown",
  "cancelled",
  "cancelled_unconfirmed",
];

/** States the backend accepts a cancel for (§11.6). */
export const IMAGE_JOB_CANCELLABLE_STATUSES: readonly ImageJobStatus[] = [
  "queued",
  "running",
  "polling",
];

export interface MediaJobCard {
  id: string;
  status: ImageJobStatus;
  status_version: number;
  operation: ImageJobOperation;
  prompt: string;
  provider: string;
  profile: string;
  protocol: string;
  model: string;
  session_id: string;
  turn_id: string;
  tool_call_id: string;
  error_code: string;
  sanitized_error: string;
  created_at: number;
  started_at: number;
  updated_at: number;
  finished_at: number;
  elapsed_seconds: number;
  poll_after: number;
  deadline_at: number;
  attempt_count: number;
  artifact_ids: string[];
  retry_of_job_id: string;
}

export interface MediaReference {
  id: string;
  owner_type: string;
  owner_id: string;
  version: number;
  created_at: number;
  is_live: boolean;
}

export interface MediaArtifact {
  id: string;
  job_id: string;
  session_id: string;
  turn_id: string;
  provider: string;
  profile: string;
  protocol: string;
  model: string;
  operation: ImageJobOperation;
  original_prompt: string;
  revised_prompt: string;
  sha256: string;
  mime_type: string;
  width: number;
  height: number;
  size_bytes: number;
  created_at: number;
  gc_candidate_since: number;
  is_gc_candidate: boolean;
  reference_count: number;
  references: MediaReference[];
  preview_url: string | null;
  download_url: string | null;
}

export interface MediaQuota {
  used_bytes: number;
  limit_bytes: number;
  reclaimable_bytes: number;
  file_count: number;
  remaining_bytes: number;
}

export interface MediaGcResult {
  deleted_count: number;
  freed_bytes: number;
  scanned_count: number;
}

export interface MediaJobSubmitBody {
  operation: ImageJobOperation;
  prompt: string;
  profile: string;
  model: string;
  protocol: string;
  size?: string;
  quality?: string;
  count?: number;
  source_artifact_ids?: string[];
  mask_artifact_id?: string;
  continuation_job_id?: string;
  /** Mandatory: §8.3 binds image-job submit to user_id + idempotency_key. */
  idempotency_key: string;
  session_id?: string;
  turn_id?: string;
  tool_call_id?: string;
  provider_options?: Record<string, unknown>;
}
