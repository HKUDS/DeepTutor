import { apiFetch, apiUrl } from "@/lib/api";
import type {
  MediaArtifact,
  MediaGcResult,
  MediaJobCard,
  MediaJobSubmitBody,
  MediaQuota,
} from "@/lib/media-types";

const MEDIA_BASE = "/api/v1";

/** Parse a sanitized backend error detail into a stable Error message. */
async function mediaError(res: Response, fallback: string): Promise<Error> {
  let detail = "";
  try {
    const body = await res.json();
    detail = typeof body?.detail === "string" ? body.detail : "";
  } catch {
    // non-JSON body — keep the fallback
  }
  return new Error(detail || `${fallback} (${res.status})`);
}

// ── image jobs ───────────────────────────────────────────────────────────────

export async function fetchMediaJobs(sessionId?: string): Promise<MediaJobCard[]> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/image-jobs${query}`));
  if (!res.ok) throw await mediaError(res, "Failed to load image jobs");
  const body = (await res.json()) as { jobs: MediaJobCard[] };
  return body.jobs;
}

export async function fetchMediaJob(jobId: string): Promise<MediaJobCard> {
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/image-jobs/${encodeURIComponent(jobId)}`));
  if (!res.ok) throw await mediaError(res, "Failed to load image job");
  const body = (await res.json()) as { job: MediaJobCard };
  return body.job;
}

export async function submitMediaJob(
  payload: MediaJobSubmitBody,
): Promise<MediaJobCard> {
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/image-jobs`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await mediaError(res, "Failed to submit image job");
  const body = (await res.json()) as { job: MediaJobCard };
  return body.job;
}

export async function cancelMediaJob(
  jobId: string,
  expectedStatusVersion?: number,
): Promise<MediaJobCard> {
  const res = await apiFetch(
    apiUrl(`${MEDIA_BASE}/image-jobs/${encodeURIComponent(jobId)}/cancel`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_status_version: expectedStatusVersion ?? null,
      }),
    },
  );
  if (!res.ok) throw await mediaError(res, "Failed to cancel image job");
  const body = (await res.json()) as { job: MediaJobCard };
  return body.job;
}

export interface MediaJobRetryOptions {
  /** Mandatory: §8.3 binds retry to job_id + expected_status_version. */
  expected_status_version: number;
  profile?: string;
  model?: string;
  protocol?: string;
}

export async function retryMediaJob(
  jobId: string,
  options: MediaJobRetryOptions,
): Promise<MediaJobCard> {
  const res = await apiFetch(
    apiUrl(`${MEDIA_BASE}/image-jobs/${encodeURIComponent(jobId)}/retry`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_status_version: options.expected_status_version,
        profile: options.profile ?? "",
        model: options.model ?? "",
        protocol: options.protocol ?? "",
      }),
    },
  );
  if (!res.ok) throw await mediaError(res, "Failed to retry image job");
  const body = (await res.json()) as { job: MediaJobCard };
  return body.job;
}

// ── generated artifacts / quota ──────────────────────────────────────────────

export async function fetchMediaArtifacts(
  sessionId?: string,
): Promise<{ artifacts: MediaArtifact[]; quota: MediaQuota }> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/generated-artifacts${query}`));
  if (!res.ok) throw await mediaError(res, "Failed to load generated media");
  return res.json() as Promise<{ artifacts: MediaArtifact[]; quota: MediaQuota }>;
}

export async function fetchMediaQuota(): Promise<MediaQuota> {
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/generated-artifacts/quota`));
  if (!res.ok) throw await mediaError(res, "Failed to load media quota");
  const body = (await res.json()) as { quota: MediaQuota };
  return body.quota;
}

export async function fetchMediaArtifact(artifactId: string): Promise<MediaArtifact> {
  const res = await apiFetch(
    apiUrl(`${MEDIA_BASE}/generated-artifacts/${encodeURIComponent(artifactId)}`),
  );
  if (!res.ok) throw await mediaError(res, "Failed to load media artifact");
  const body = (await res.json()) as { artifact: MediaArtifact };
  return body.artifact;
}

export async function detachMediaReference(
  artifactId: string,
  referenceId: string,
  expectedVersion?: number,
): Promise<MediaArtifact> {
  const res = await apiFetch(
    apiUrl(
      `${MEDIA_BASE}/generated-artifacts/${encodeURIComponent(artifactId)}/references/${encodeURIComponent(referenceId)}`,
    ),
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: expectedVersion ?? null }),
    },
  );
  if (!res.ok) throw await mediaError(res, "Failed to detach reference");
  const body = (await res.json()) as { artifact: MediaArtifact };
  return body.artifact;
}

export interface MediaDeleteOptions {
  mode: "detach_current" | "remove_everywhere";
  confirmed?: boolean;
  owner_type?: string;
  owner_id?: string;
}

export async function deleteMediaArtifact(
  artifactId: string,
  options: MediaDeleteOptions,
): Promise<MediaArtifact> {
  const res = await apiFetch(
    apiUrl(`${MEDIA_BASE}/generated-artifacts/${encodeURIComponent(artifactId)}/delete`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: options.mode,
        confirmed: options.confirmed ?? false,
        owner_type: options.owner_type ?? null,
        owner_id: options.owner_id ?? "",
      }),
    },
  );
  if (!res.ok) throw await mediaError(res, "Failed to delete media");
  const body = (await res.json()) as { artifact: MediaArtifact };
  return body.artifact;
}

export async function runMediaGc(): Promise<MediaGcResult> {
  const res = await apiFetch(apiUrl(`${MEDIA_BASE}/generated-artifacts/gc`), {
    method: "POST",
  });
  if (!res.ok) throw await mediaError(res, "Failed to clean up media");
  const body = (await res.json()) as { result: MediaGcResult };
  return body.result;
}

/** Authenticated same-user route that serves the artifact bytes (§12.3). */
export function mediaFileUrl(
  artifact: Pick<MediaArtifact, "id">,
  disposition: "inline" | "attachment" = "inline",
): string {
  return `/api/v1/generated-artifacts/${encodeURIComponent(artifact.id)}/file?disposition=${disposition}`;
}
