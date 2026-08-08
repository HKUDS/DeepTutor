import { apiFetch, apiUrl } from "@/lib/api";

export type InstallMode =
  "pypi" | "source_web" | "source_cli" | "docker" | "unsupported";

export type UpdateStatus = "available" | "up_to_date" | "failed";

export interface UpdateCheckResponse {
  status: UpdateStatus;
  current_version: string;
  latest_version: string | null;
  install_mode: InstallMode;
  can_auto_update: boolean;
  release_url: string | null;
  detail: string;
}

export type UpdateJobStatus =
  "pending" | "handoff" | "running" | "restarting" | "succeeded" | "failed";

export interface UpdateJobResponse {
  id: string;
  status: UpdateJobStatus;
  current_version: string;
  target_version: string;
  error: string | null;
  restart_count: number;
}

async function responseError(response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") return new Error(payload.detail);
  } catch {
    // Fall through to the status-only message for non-JSON responses.
  }
  return new Error(`Update request failed (HTTP ${response.status})`);
}

export async function fetchUpdateStatus(
  signal?: AbortSignal,
): Promise<UpdateCheckResponse> {
  const response = await apiFetch(apiUrl("/api/v1/system/update"), {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as UpdateCheckResponse;
}

export async function requestWebUpdate(): Promise<UpdateJobResponse> {
  const response = await apiFetch(apiUrl("/api/v1/system/update"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: "update-and-restart" }),
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as UpdateJobResponse;
}

export async function fetchUpdateJob(
  signal?: AbortSignal,
): Promise<UpdateJobResponse | null> {
  const response = await apiFetch(apiUrl("/api/v1/system/update/job"), {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as UpdateJobResponse | null;
}
