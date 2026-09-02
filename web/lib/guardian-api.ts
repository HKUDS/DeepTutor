import { apiFetch, apiUrl } from "@/lib/api";

export interface GuardianRelationship {
  id: string;
  guardian_user_id: string;
  guardian_username: string;
  learner_user_id: string;
  learner_username: string;
  permissions: string[];
  revoked_at?: string | null;
}

export interface GuardianReport {
  learner: { id: string; username: string; disabled: boolean };
  assigned_materials: Array<{
    book_id: string;
    title?: string;
    permission: string;
  }>;
  grant_summary: {
    model_count: number;
    knowledge_base_count: number;
    skill_count: number;
  };
}

export interface GuardianMaterial {
  book_id: string;
  title?: string;
  assigned: boolean;
  permission: string;
}

export interface GuardianRestrictions {
  age_band: "6-8" | "9-12" | "13-15";
  allow_upload: boolean;
  allowed_surfaces: Array<"chat" | "reading">;
  extensions: string[];
}

export interface GuardianExtension {
  id: string;
  name: string;
  version: string;
}

function extractDetail(value: unknown): string | null {
  if (typeof value !== "object" || value === null || !("detail" in value)) {
    return null;
  }
  const detail = (value as { detail: unknown }).detail;
  return typeof detail === "string" ? detail : null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(apiUrl(path), init);
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new Error(extractDetail(data) ?? "Request failed");
  return data as T;
}

export async function listGuardianRelationships(): Promise<
  GuardianRelationship[]
> {
  const data = await request<{ relationships: GuardianRelationship[] }>(
    "/api/multi-user/me/guardianships",
  );
  return data.relationships;
}

export async function listAdminGuardianRelationships(): Promise<
  GuardianRelationship[]
> {
  const data = await request<{ relationships: GuardianRelationship[] }>(
    "/api/multi-user/guardians",
  );
  return data.relationships;
}

export async function authorizeGuardianRelationship(
  guardianId: string,
  learnerId: string,
  permissions: string[],
): Promise<GuardianRelationship> {
  const data = await request<{ relationship: GuardianRelationship }>(
    "/api/multi-user/guardians",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        guardian_user_id: guardianId,
        learner_user_id: learnerId,
        permissions,
      }),
    },
  );
  return data.relationship;
}

export async function revokeGuardianRelationship(
  relationshipId: string,
): Promise<void> {
  await request(
    `/api/multi-user/guardians/${encodeURIComponent(relationshipId)}`,
    { method: "DELETE" },
  );
}

export async function revokeMyGuardianRelationship(
  relationshipId: string,
): Promise<void> {
  await request(
    `/api/multi-user/me/guardianships/${encodeURIComponent(relationshipId)}`,
    { method: "DELETE" },
  );
}

export function getGuardianReport(learnerId: string): Promise<GuardianReport> {
  return request<GuardianReport>(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/guardian-report`,
  );
}

export async function resetLearnerCredentials(
  learnerId: string,
  newPassword: string,
): Promise<void> {
  await request(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/credentials/reset`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    },
  );
}

export async function getGuardianMaterials(
  learnerId: string,
): Promise<GuardianMaterial[]> {
  const data = await request<{ materials: GuardianMaterial[] }>(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/materials`,
  );
  return data.materials;
}

export async function saveGuardianMaterials(
  learnerId: string,
  bookIds: string[],
): Promise<void> {
  await request(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/materials`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ book_ids: bookIds }),
    },
  );
}

export async function getGuardianRestrictions(learnerId: string): Promise<{
  restrictions: GuardianRestrictions;
  available_extensions: GuardianExtension[];
}> {
  return request(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/restrictions`,
  );
}

export async function saveGuardianRestrictions(
  learnerId: string,
  restrictions: GuardianRestrictions,
): Promise<GuardianRestrictions> {
  const data = await request<{ restrictions: GuardianRestrictions }>(
    `/api/multi-user/learners/${encodeURIComponent(learnerId)}/restrictions`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(restrictions),
    },
  );
  return data.restrictions;
}
