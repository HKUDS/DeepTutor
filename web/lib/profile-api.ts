import { apiFetch, apiUrl } from "@/lib/api";

export interface ProfileInfo {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
  disabled?: boolean;
  /** Avatar marker: "", "icon:<name>:<color>", or "img:<version>". */
  avatar?: string;
}

function extractDetail(data: unknown, fallback: string): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/** Fetch the signed-in user's own profile. */
export async function getProfile(): Promise<ProfileInfo> {
  const res = await apiFetch(apiUrl("/api/v1/auth/profile"));
  if (!res.ok) throw new Error("Failed to fetch profile");
  return res.json();
}

/**
 * Persist an icon-based avatar choice ("icon:<name>:<color>") or reset to the
 * deterministic fallback (""). Uploaded-image markers are managed by
 * `uploadAvatarImage`.
 */
export async function setAvatarMarker(avatar: string): Promise<string> {
  const res = await apiFetch(apiUrl("/api/v1/auth/profile"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ avatar }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(extractDetail(data, "Failed to update avatar"));
  }
  const data = await res.json();
  return String(data.avatar ?? avatar);
}

/** Upload an avatar image (already cropped/resized client-side). */
export async function uploadAvatarImage(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", blob, "avatar");
  const res = await apiFetch(apiUrl("/api/v1/auth/profile/avatar"), {
    method: "PUT",
    body: form,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(extractDetail(data, "Failed to upload avatar"));
  }
  const data = await res.json();
  return String(data.avatar ?? "");
}

/** Remove the uploaded avatar image and reset the marker. */
export async function removeAvatarImage(): Promise<void> {
  const res = await apiFetch(apiUrl("/api/v1/auth/profile/avatar"), {
    method: "DELETE",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(extractDetail(data, "Failed to remove avatar"));
  }
}

/** Build the image URL for an "img:<version>" marker (version cache-busts). */
export function avatarImageUrl(userId: string, marker: string): string {
  const version = marker.startsWith("img:") ? marker.slice(4) : "0";
  return apiUrl(
    `/api/v1/auth/avatar/${encodeURIComponent(userId)}?v=${encodeURIComponent(version)}`,
  );
}
