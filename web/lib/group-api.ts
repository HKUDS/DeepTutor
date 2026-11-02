/**
 * Client for the group endpoints (`deeptutor/multi_user/groups.py`).
 *
 * A group is an administrative container with exactly one lead. The lead is an
 * ordinary user: every call here is authorised server-side against the group's
 * `lead_user_id`, so the client never sends a role and never infers one.
 */

import { apiFetch, apiUrl } from "@/shared/api/client";

export interface GroupAccount {
  id: string;
  username: string;
  role?: string;
  preset?: string;
  disabled?: boolean;
  /** Set when the account was deleted after being placed in the group. */
  missing?: boolean;
}

export interface Group {
  id: string;
  name: string;
  lead_user_id: string;
  member_user_ids: string[];
  created_at: string;
  created_by: string;
  updated_at: string;
  lead: GroupAccount;
  members: GroupAccount[];
}

export interface GroupReportEntry {
  user_id: string;
  username: string;
  role: string;
  preset: string;
  disabled: boolean;
  must_change_password: boolean;
  last_active_at: string | null;
  grant_summary: {
    model_count: number;
    knowledge_base_count: number;
    skill_count: number;
  };
}

export interface GrantableModel {
  profile_id: string;
  name?: string;
  model_ids: string[];
}

export interface GrantableResource {
  name?: string;
  kb_name?: string;
  resource_id?: string;
  id?: string;
  skill_id?: string;
}

export interface GrantableResources {
  models: GrantableModel[];
  knowledge_bases: GrantableResource[];
  skills: GrantableResource[];
}

export interface GroupMemberGrant {
  models: Array<{ profile_id: string; model_ids: string[] }>;
  knowledge_bases: Array<{ name: string }>;
  skills: Array<{ skill_id: string }>;
}

/** Stored entries are looser than the payload: the server keeps the grant verbatim. */
export interface MemberGrantSnapshot {
  models: Array<{ profile_id: string; name?: string; model_ids?: string[] }>;
  knowledge_bases: Array<{
    name?: string;
    kb_name?: string;
    resource_id?: string;
    id?: string;
  }>;
  skills: Array<{ skill_id?: string; id?: string }>;
}

function detailFrom(data: unknown): string | null {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(path), init);
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(detailFrom(data) ?? "Request failed");
  }
  return data as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function listGroups(): Promise<Group[]> {
  const data = await request<{ groups: Group[] }>("/api/multi-user/groups");
  return data.groups;
}

export async function getGroup(groupId: string): Promise<Group> {
  const data = await request<{ group: Group }>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}`,
  );
  return data.group;
}

export async function createGroupMember(
  groupId: string,
  username: string,
  password: string,
): Promise<Group> {
  const data = await request<{ group: Group }>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/members`,
    jsonInit("POST", { username, password }),
  );
  return data.group;
}

export async function removeGroupMember(
  groupId: string,
  username: string,
): Promise<Group> {
  const data = await request<{ group: Group }>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(username)}`,
    { method: "DELETE" },
  );
  return data.group;
}

export async function resetGroupMemberPassword(
  groupId: string,
  username: string,
  newPassword: string,
): Promise<void> {
  await request(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(username)}/password`,
    jsonInit("PUT", { new_password: newPassword }),
  );
}

export async function getGroupGrantable(
  groupId: string,
): Promise<GrantableResources> {
  return request<GrantableResources>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/grantable`,
  );
}

/** The member's current assignable surface, so an edit never silently revokes. */
export async function getGroupMemberGrants(
  groupId: string,
  username: string,
): Promise<MemberGrantSnapshot> {
  return request<MemberGrantSnapshot>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(username)}/grants`,
  );
}

export async function setGroupMemberGrants(
  groupId: string,
  username: string,
  grant: GroupMemberGrant,
): Promise<void> {
  await request(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(username)}/grants`,
    jsonInit("PUT", grant),
  );
}

export async function getGroupReport(
  groupId: string,
): Promise<{ group: Group; members: GroupReportEntry[] }> {
  return request<{ group: Group; members: GroupReportEntry[] }>(
    `/api/multi-user/groups/${encodeURIComponent(groupId)}/report`,
  );
}
