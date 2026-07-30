import { apiFetch, apiUrl } from "@/lib/api";

export interface UserRecord {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
  disabled?: boolean;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
}

export async function listUsers(): Promise<UserRecord[]> {
  const res = await apiFetch(apiUrl("/api/v1/auth/users"));
  if (!res.ok) throw new Error("Failed to fetch users");
  return res.json();
}

export async function deleteUser(username: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/auth/users/${encodeURIComponent(username)}`),
    {
      method: "DELETE",
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to delete user");
  }
}

export async function setUserRole(
  username: string,
  role: "admin" | "user",
): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/auth/users/${encodeURIComponent(username)}/role`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to update role");
  }
}

export interface CreatedUser {
  user_id: string;
  username: string;
  role: "admin" | "user";
  is_admin: boolean;
}

export interface LlmQuota {
  daily_tokens: number;
  monthly_tokens: number;
}

export interface EmbeddingQuota extends LlmQuota {}

export interface MineruQuota {
  daily_pages: number;
  monthly_pages: number;
  max_pages_per_file: number;
}

export interface ResourceQuota {
  llm: LlmQuota;
  embedding: EmbeddingQuota;
  mineru: MineruQuota;
}

/** @deprecated Use ResourceQuota. Kept for callers that only manage LLM limits. */
export type DefaultTokenQuota = LlmQuota;

export async function fetchDefaultQuota(): Promise<ResourceQuota> {
  const res = await apiFetch(apiUrl("/api/v1/multi-user/admin/default-quota"));
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail ?? "Failed to load default quota");
  }
  const data = (await res.json()) as {
    default_quota: ResourceQuota;
  };
  return data.default_quota;
}

export async function saveDefaultQuota(
  quota: ResourceQuota,
): Promise<ResourceQuota> {
  const res = await apiFetch(apiUrl("/api/v1/multi-user/admin/default-quota"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ default_quota: quota }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail ?? "Failed to save default quota");
  }
  const data = (await res.json()) as {
    default_quota: ResourceQuota;
  };
  return data.default_quota;
}

/** @deprecated Use fetchDefaultQuota. */
export async function fetchDefaultTokenQuota(): Promise<LlmQuota> {
  return (await fetchDefaultQuota()).llm;
}

/** @deprecated Use saveDefaultQuota. */
export async function saveDefaultTokenQuota(
  quota: LlmQuota,
): Promise<LlmQuota> {
  const current = await fetchDefaultQuota();
  return (
    await saveDefaultQuota({
      ...current,
      llm: quota,
    })
  ).llm;
}

export async function createUser(
  username: string,
  password: string,
): Promise<CreatedUser> {
  const res = await apiFetch(apiUrl("/api/v1/auth/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) && detail.length > 0 && detail[0]?.msg
          ? String(detail[0].msg)
          : "Failed to create user";
    throw new Error(message);
  }
  return (await res.json()) as CreatedUser;
}
