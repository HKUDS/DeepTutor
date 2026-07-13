import { apiFetch, apiUrl } from "@/lib/api";
import type { GrantPayload, MultiUserResources } from "./types";

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return String(data?.detail || fallback);
  } catch {
    return fallback;
  }
}

export async function fetchAdminResources(): Promise<MultiUserResources> {
  const res = await apiFetch(apiUrl("/api/v1/multi-user/admin/resources"));
  if (!res.ok)
    throw new Error(
      await readError(res, "Failed to load assignable resources"),
    );
  return (await res.json()) as MultiUserResources;
}

export async function fetchUserGrant(userId: string): Promise<GrantPayload> {
  const res = await apiFetch(
    apiUrl(`/api/v1/multi-user/users/${encodeURIComponent(userId)}/grants`),
  );
  if (!res.ok)
    throw new Error(await readError(res, "Failed to load user grant"));
  const data = await res.json();
  return data.grant as GrantPayload;
}

export async function saveUserGrant(
  userId: string,
  grant: GrantPayload,
): Promise<GrantPayload> {
  const res = await apiFetch(
    apiUrl(`/api/v1/multi-user/users/${encodeURIComponent(userId)}/grants`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant }),
    },
  );
  if (!res.ok)
    throw new Error(await readError(res, "Failed to save user grant"));
  const data = await res.json();
  return data.grant as GrantPayload;
}
