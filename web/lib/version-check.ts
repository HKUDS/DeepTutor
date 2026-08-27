import { apiFetch, apiUrl } from "@/lib/api";

export type LatestRelease = {
  tag_name: string;
  name: string;
  published_at: string;
  html_url: string;
  excerpt: string;
  update_available: boolean;
  migration_bearing: boolean;
};

export type VersionInstallation = {
  mode: "pypi" | "source" | "docker" | "unknown";
  update_supported: boolean;
  command: string;
  reason: string;
};

export type VersionUpdate = {
  state: "idle" | "running" | "done" | "failed" | "cancelled";
  message: string;
  previous_version: string;
  installed_version: string;
  target_version: string;
  restart_required: boolean;
  lines: string[];
};

export type LastVersionUpdate = {
  previous_version: string;
  installed_version: string;
  target_version: string;
  updated_at: string;
};

export type VersionStatus = {
  current_version: string;
  latest_release: LatestRelease | null;
  checked_at: string;
  cached: boolean;
  check_enabled: boolean;
  installation: VersionInstallation;
  update: VersionUpdate;
  last_update: LastVersionUpdate | null;
};

export function compareVersionTags(
  candidate: string | null | undefined,
  current: string | null | undefined,
): number | null {
  const candidateMatch = candidate?.trim().match(/^v?(\d+)\.(\d+)\.(\d+)/);
  const currentMatch = current?.trim().match(/^v?(\d+)\.(\d+)\.(\d+)/);
  if (!candidateMatch || !currentMatch) return null;

  for (let index = 1; index <= 3; index += 1) {
    const delta = Number(candidateMatch[index]) - Number(currentMatch[index]);
    if (delta !== 0) return delta;
  }
  return 0;
}

export function isUpdateAvailable(
  latest: LatestRelease | null,
  currentVersion: string | null | undefined,
): boolean {
  if (latest?.update_available !== undefined) return latest.update_available;
  return (compareVersionTags(latest?.tag_name, currentVersion) ?? -1) > 0;
}

async function requestVersionStatus(
  path: string,
  init?: RequestInit,
): Promise<VersionStatus> {
  const response = await apiFetch(apiUrl(path), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error("Unable to update version status");
  }
  return (await response.json()) as VersionStatus;
}

export function getVersionStatus(): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version");
}

export function checkVersionUpdates(force = true): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version/check", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function updateVersionCheckSettings(
  checkEnabled: boolean,
): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version/settings", {
    method: "PUT",
    body: JSON.stringify({ check_enabled: checkEnabled }),
  });
}

export function startVersionUpdate(): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version/update", {
    method: "POST",
  });
}

export function getVersionUpdateStatus(): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version/update/status");
}

export function cancelVersionUpdate(): Promise<VersionStatus> {
  return requestVersionStatus("/api/v1/settings/version/update/cancel", {
    method: "POST",
  });
}
