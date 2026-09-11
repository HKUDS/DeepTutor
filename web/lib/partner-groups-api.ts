/** Typed client for first-class Partner Groups. */

import { apiFetch, apiUrl } from "@/lib/api";
import { browserStorage } from "@/shared/storage";
import type { PartnerInfo } from "@/lib/partners-api";
import type { StreamEvent } from "@/features/chat/model/protocol";

export interface PartnerGroupMember extends Pick<
  PartnerInfo,
  | "partner_id"
  | "name"
  | "description"
  | "emoji"
  | "color"
  | "avatar"
  | "running"
> {}

export interface PartnerGroup {
  group_id: string;
  owner_id: string;
  name: string;
  description: string;
  member_ids: string[];
  members: PartnerGroupMember[];
  discussion_mode: "panel_parallel" | string;
  shared_memory: "whiteboard" | string;
  emoji: string;
  color: string;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface PartnerGroupMessage {
  event_id: string;
  turn_id: string;
  session_key: string;
  role: "user" | "partner";
  content: string;
  author_id: string;
  author_name: string;
  created_at: string;
  mentions: string[];
  error: boolean;
  kind: "message" | "invocation_question" | "invocation_reply" | string;
  events: StreamEvent[];
  invocation_id: string;
  invocation: PartnerInvocation | null;
}

export interface PartnerInvocation {
  invocation_id: string;
  group_id: string;
  session_key: string;
  parent_turn_id: string;
  requester_partner_id: string;
  requester_partner_name: string;
  target_partner_id: string;
  target_partner_name: string;
  question: string;
  status: "pending" | "approved" | "rejected" | "completed" | "failed" | string;
  created_at: string;
  updated_at: string;
  question_event_id: string;
  reply_event_id: string;
  error: string;
}

export interface WhiteboardEntry {
  entry_id: string;
  turn_id: string;
  session_key: string;
  author_id: string;
  author_name: string;
  content: string;
  mentions: string[];
  created_at: string;
}

export interface CreatePartnerGroupPayload {
  name: string;
  description?: string;
  member_ids: string[];
  discussion_mode?: string;
  shared_memory?: string;
  emoji?: string;
  color?: string;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function listPartnerGroups(): Promise<PartnerGroup[]> {
  return json(
    await apiFetch(apiUrl("/api/partner-groups"), { cache: "no-store" }),
  );
}

export async function getPartnerGroup(groupId: string): Promise<PartnerGroup> {
  return json(
    await apiFetch(
      apiUrl(`/api/partner-groups/${encodeURIComponent(groupId)}`),
      {
        cache: "no-store",
      },
    ),
  );
}

export async function createPartnerGroup(
  payload: CreatePartnerGroupPayload,
): Promise<PartnerGroup> {
  return json(
    await apiFetch(apiUrl("/api/partner-groups"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function updatePartnerGroup(
  groupId: string,
  payload: Partial<CreatePartnerGroupPayload>,
): Promise<PartnerGroup> {
  return json(
    await apiFetch(
      apiUrl(`/api/partner-groups/${encodeURIComponent(groupId)}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function deletePartnerGroup(groupId: string): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`/api/partner-groups/${encodeURIComponent(groupId)}`),
      {
        method: "DELETE",
      },
    ),
  );
}

export async function getPartnerGroupHistory(
  groupId: string,
  sessionKey: string,
): Promise<PartnerGroupMessage[]> {
  const query = new URLSearchParams({ session_key: sessionKey });
  return json(
    await apiFetch(
      apiUrl(
        `/api/partner-groups/${encodeURIComponent(groupId)}/history?${query}`,
      ),
      { cache: "no-store" },
    ),
  );
}

export async function getPartnerGroupWhiteboard(
  groupId: string,
): Promise<WhiteboardEntry[]> {
  return json(
    await apiFetch(
      apiUrl(`/api/partner-groups/${encodeURIComponent(groupId)}/whiteboard`),
      { cache: "no-store" },
    ),
  );
}

export async function getPartnerGroupInvocations(
  groupId: string,
  sessionKey: string,
): Promise<PartnerInvocation[]> {
  const query = new URLSearchParams({ session_key: sessionKey });
  return json(
    await apiFetch(
      apiUrl(
        `/api/partner-groups/${encodeURIComponent(groupId)}/invocations?${query}`,
      ),
      { cache: "no-store" },
    ),
  );
}

export function partnerGroupSessionKey(groupId: string): string {
  const storageKey = `deeptutor:partner-group:${groupId}:session`;
  if (typeof window === "undefined") return "default";
  const existing = browserStorage.readRaw("local", storageKey);
  if (existing) return existing;
  const created = `group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  browserStorage.writeRaw("local", storageKey, created);
  return created;
}

export interface PartnerGroupSession {
  session_key: string;
  title: string;
  message_count: number;
  updated_at: string;
  created_at: string;
}

export async function listPartnerGroupSessions(
  groupId: string,
): Promise<PartnerGroupSession[]> {
  return json(
    await apiFetch(
      apiUrl(`/api/partner-groups/${encodeURIComponent(groupId)}/sessions`),
      { cache: "no-store" },
    ),
  );
}

export async function deletePartnerGroupSession(
  groupId: string,
  sessionKey: string,
): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(
        `/api/partner-groups/${encodeURIComponent(groupId)}/sessions/${encodeURIComponent(sessionKey)}`,
      ),
      { method: "DELETE" },
    ),
  );
}

/** Point this group at another (or brand new) discussion thread. */
export function setPartnerGroupSessionKey(groupId: string, key: string): void {
  if (typeof window === "undefined") return;
  browserStorage.writeRaw(
    "local",
    `deeptutor:partner-group:${groupId}:session`,
    key,
  );
}

export function createPartnerGroupSessionKey(groupId: string): string {
  const created = `group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  setPartnerGroupSessionKey(groupId, created);
  return created;
}

export interface DiscussionMode {
  name: string;
  label: string;
  description: string;
}

export async function listDiscussionModes(): Promise<DiscussionMode[]> {
  return json(
    await apiFetch(apiUrl("/api/partner-groups/discussion-modes"), {
      cache: "no-store",
    }),
  );
}
