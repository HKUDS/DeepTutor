import { apiFetch, apiUrl } from "@/lib/api";
import type { ByokProfile, ByokService, ByokSource, ByokStatus } from "./types";

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return String(body?.detail || fallback);
  } catch {
    return fallback;
  }
}

export async function fetchByokStatus(): Promise<ByokStatus> {
  const response = await apiFetch(apiUrl("/api/v1/byok/status"));
  if (!response.ok) throw new Error(await readError(response, "无法读取 BYOK 配置"));
  return (await response.json()) as ByokStatus;
}

export async function saveByokProfile(payload: {
  profileId?: string;
  service: ByokService;
  provider: string;
  name?: string;
  model?: string;
  baseUrl?: string;
  dimension?: number;
  mode?: string;
  generation?: number;
  secret?: string;
}): Promise<ByokProfile> {
  const body = {
    service: payload.service,
    provider: payload.provider,
    name: payload.name || "",
    model: payload.model || "",
    base_url: payload.baseUrl || null,
    dimension: payload.dimension || 0,
    mode: payload.mode || "",
    ...(payload.generation ? { generation: payload.generation } : {}),
    ...(payload.secret ? { secret: payload.secret } : {}),
  };
  const endpoint = payload.profileId
    ? `/api/v1/byok/profiles/${encodeURIComponent(payload.profileId)}`
    : "/api/v1/byok/profiles";
  const response = await apiFetch(apiUrl(endpoint), {
    method: payload.profileId ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await readError(response, "无法保存 BYOK 配置"));
  const data = await response.json();
  return data.profile as ByokProfile;
}

export async function deleteByokProfile(profileId: string): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/byok/profiles/${encodeURIComponent(profileId)}`),
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(await readError(response, "无法删除 BYOK 配置"));
}

export async function setByokPreference(
  service: ByokService,
  source: ByokSource,
  profileId?: string,
): Promise<void> {
  const response = await apiFetch(apiUrl("/api/v1/byok/preferences"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service, source, profile_id: profileId || null }),
  });
  if (!response.ok) throw new Error(await readError(response, "无法切换资源来源"));
}
