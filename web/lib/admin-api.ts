import { apiFetch, apiUrl } from "@/lib/api";

export type AccountPreset = "standard" | "learner" | "custom";

export interface UserRecord {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
  disabled?: boolean;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
  preset?: AccountPreset;
  book_permission?: {
    create: boolean;
    default: "none" | "read";
    books: Record<string, "none" | "read" | "edit">;
  };
}

export interface LearnerProfile {
  age?: number;
  grade_level?: string;
  curriculum?: string;
  language?: string;
  reading_level?: string;
  explanation_style?: string;
}

export async function getLearnerProfile(
  username: string,
): Promise<LearnerProfile | null> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/learner-profile`),
  );
  if (!res.ok) throw new Error("Failed to fetch learner profile");
  const data = (await res.json()) as {
    learner_profile?: LearnerProfile | null;
  };
  return data.learner_profile ?? null;
}

export async function setLearnerProfile(
  username: string,
  profile: LearnerProfile,
): Promise<LearnerProfile | null> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/learner-profile`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? "Failed to save learner profile");
  }
  const data = (await res.json()) as {
    learner_profile?: LearnerProfile | null;
  };
  return data.learner_profile ?? null;
}

export async function listUsers(): Promise<UserRecord[]> {
  const res = await apiFetch(apiUrl("/api/auth/users"));
  if (!res.ok) throw new Error("Failed to fetch users");
  return res.json();
}

export async function deleteUser(username: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}`),
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
    apiUrl(`/api/auth/users/${encodeURIComponent(username)}/role`),
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
  preset: AccountPreset;
}

export async function createUser(
  username: string,
  password: string,
  preset: AccountPreset = "standard",
): Promise<CreatedUser> {
  const res = await apiFetch(apiUrl("/api/auth/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, preset }),
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
