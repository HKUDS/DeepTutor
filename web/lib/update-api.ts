import { apiFetch, apiUrl } from "@/lib/api";

export type InstallMode =
  | "pypi"
  | "source_web"
  | "source_cli"
  | "docker"
  | "unsupported";

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

export async function fetchUpdateStatus(
  signal?: AbortSignal,
): Promise<UpdateCheckResponse> {
  const response = await apiFetch(apiUrl("/api/v1/system/update"), {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Update check failed (HTTP ${response.status})`);
  }
  return (await response.json()) as UpdateCheckResponse;
}
