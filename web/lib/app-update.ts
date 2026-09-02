import { apiFetch, apiUrl } from "@/lib/api";

export type InstallMode = "pypi" | "source" | "docker" | "unknown";
export type UpdateJobStatus =
  | "pending"
  | "handoff"
  | "running"
  | "restarting"
  | "succeeded"
  | "failed";

export interface UpdateRelease {
  version: string;
  name: string;
  published_at: string;
  url: string;
  excerpt: string;
  migration_warning: boolean;
}

export interface UpdateJob {
  id: string;
  status: UpdateJobStatus;
  current_version: string;
  target_version: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  restart_count: number;
}

export interface AppUpdateStatus {
  current_version: string;
  check_enabled: boolean;
  checked_at: string;
  cached: boolean;
  check_error: string;
  update_available: boolean;
  release: UpdateRelease | null;
  installation: {
    mode: InstallMode;
    automatic_update: boolean;
    command: string;
    reason: string;
  };
  launcher_managed: boolean;
  is_admin: boolean;
  job: UpdateJob | null;
}

export interface AppUpdateStatusSignal {
  status?: AppUpdateStatus;
  error: string;
}

type AppUpdateStatusListener = (signal: AppUpdateStatusSignal) => void;

const appUpdateStatusListeners = new Set<AppUpdateStatusListener>();

function publishAppUpdateStatus(signal: AppUpdateStatusSignal): void {
  for (const listener of appUpdateStatusListeners) listener(signal);
}

/** Keep compact version surfaces in sync with checks performed on the About page. */
export function subscribeAppUpdateStatus(
  listener: AppUpdateStatusListener,
): () => void {
  appUpdateStatusListeners.add(listener);
  return () => appUpdateStatusListeners.delete(listener);
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

async function readStatus(response: Response): Promise<AppUpdateStatus> {
  if (!response.ok) {
    const error = await responseError(response);
    publishAppUpdateStatus({ error: error.message });
    throw error;
  }
  try {
    const status = (await response.json()) as AppUpdateStatus;
    publishAppUpdateStatus({ status, error: status.check_error });
    return status;
  } catch (cause) {
    const error =
      cause instanceof Error
        ? cause
        : new Error("Unable to read update status");
    publishAppUpdateStatus({ error: error.message });
    throw error;
  }
}

export async function fetchAppUpdateStatus(
  signal?: AbortSignal,
): Promise<AppUpdateStatus> {
  return readStatus(
    await apiFetch(apiUrl("/api/system/update"), {
      cache: "no-store",
      signal,
    }),
  );
}

export async function checkAppUpdate(): Promise<AppUpdateStatus> {
  return readStatus(
    await apiFetch(apiUrl("/api/system/update/check"), {
      method: "POST",
    }),
  );
}

export async function setAppUpdateChecks(
  enabled: boolean,
): Promise<AppUpdateStatus> {
  return readStatus(
    await apiFetch(apiUrl("/api/system/update/settings"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function requestAppUpdate(): Promise<UpdateJob> {
  const response = await apiFetch(apiUrl("/api/system/update"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: "update-and-restart" }),
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as UpdateJob;
}

export async function fetchAppUpdateJob(
  signal?: AbortSignal,
): Promise<UpdateJob | null> {
  const response = await apiFetch(apiUrl("/api/system/update/job"), {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as UpdateJob | null;
}

export function updateJobIsActive(status: UpdateJobStatus): boolean {
  return ["pending", "handoff", "running", "restarting"].includes(status);
}
