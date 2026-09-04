import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";
import type { LLMSelection, StreamEvent } from "@/features/chat/model/protocol";
import { browserReturnPath, loginHref } from "@/shared/auth/return-url";

export interface SessionMessage {
  id: number;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
  events: StreamEvent[];
  attachments: Array<{
    type: string;
    filename?: string;
    base64?: string;
    url?: string;
    mime_type?: string;
    id?: string;
    extracted_text?: string;
    generated?: boolean;
    size_bytes?: number;
  }>;
  metadata?: Record<string, unknown>;
  trace?: MessageTraceMetadata;
  created_at: number;
  /** Edit-branching: id of the message this row continues. `null` for the
   *  first message in a session. Siblings share the same parent. */
  parent_message_id?: number | null;
}

export interface MessageTraceMetadata {
  turn_id?: string | null;
  total?: number;
  last_seq?: number;
  truncated?: boolean;
}

export interface MessageTracePage {
  session_id: string;
  message_id: number;
  turn_id?: string | null;
  events: StreamEvent[];
  total: number;
  last_seq: number;
  next_seq: number | null;
  complete: boolean;
}

export interface SessionPreferences {
  capability?: string;
  /** Stable learning surface, independent of the action used for a turn. */
  workspace_mode?: "immersive_reading" | "mastery_path" | "";
  tools?: string[];
  knowledge_bases?: string[];
  language?: string;
  llm_selection?: LLMSelection | null;
  /** Persistent mastery state associated with this conversation. */
  mastery_path_id?: string;
  /** Session-level persona preference; "" / absent = Default (no persona). */
  persona?: string;
  /** Edit-branching: maps a parent_message_id → the child id currently
   *  shown at that branch point. Missing keys default to the latest
   *  sibling (most recently created child). */
  selected_branches?: Record<string, number>;
  /** Study-course organization. Empty/absent means Unclassified. */
  course_id?: string;
  /** Source conversation for nested selected-text tutor threads. */
  parent_session_id?: string;
  session_kind?: "chat" | "selection_tutor" | "immersive_reading";
  /** Owning Immersive Reading workspace, present only for reading sessions. */
  reading_workspace_id?: string;
  /** Material active when the reading conversation was created. */
  reading_material_id?: string;
  pinned?: boolean;
  archived?: boolean;
}

export interface SessionSummary {
  id: string;
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  last_message: string;
  status?:
    | "idle"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "rejected";
  active_turn_id?: string;
  preferences?: SessionPreferences;
}

export interface ActiveTurnSummary {
  id: string;
  turn_id: string;
  session_id: string;
  capability: string;
  status: "running" | "completed" | "failed" | "cancelled" | "rejected";
  error: string;
  created_at: number;
  updated_at: number;
  finished_at?: number | null;
  last_seq: number;
}

export interface SessionDetail {
  id: string;
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  status?:
    | "idle"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "rejected";
  active_turn_id?: string;
  compressed_summary?: string;
  summary_up_to_msg_id?: number;
  preferences?: SessionPreferences;
  messages: SessionMessage[];
  active_turns?: ActiveTurnSummary[];
}

export interface QuizResultItem {
  question_id?: string;
  question: string;
  question_type?: string;
  options?: Record<string, string>;
  user_answer: string;
  correct_answer: string;
  explanation?: string;
  difficulty?: string;
  is_correct: boolean;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.href = loginHref(browserReturnPath(window.location));
    return new Promise(() => {});
  }
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listSessions(
  limit = 50,
  offset = 0,
  options?: { force?: boolean },
): Promise<SessionSummary[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return withClientCache<SessionSummary[]>(
    `sessions:${limit}:${offset}`,
    async () => {
      const response = await apiFetch(
        apiUrl(`/api/sessions?${qs.toString()}`),
        {
          cache: "no-store",
        },
      );
      const data = await expectJson<{ sessions: SessionSummary[] }>(response);
      return data.sessions ?? [];
    },
    {
      force: options?.force,
      ttlMs: 15_000,
    },
  );
}

/** Fetch the complete session index in bounded pages for course organization. */
export async function listAllSessions(options?: {
  force?: boolean;
}): Promise<SessionSummary[]> {
  const pageSize = 200;
  const sessions: SessionSummary[] = [];
  for (let offset = 0; ; offset += pageSize) {
    const page = await listSessions(pageSize, offset, options);
    sessions.push(...page);
    if (page.length < pageSize) return sessions;
  }
}

export async function getSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionDetail> {
  const response = await apiFetch(apiUrl(`/api/sessions/${sessionId}`), {
    cache: "no-store",
    signal,
  });
  return expectJson<SessionDetail>(response);
}

/**
 * One line the user is likely to type next, for the home composer's
 * placeholder — "" when there is nothing worth offering (no exchange yet,
 * a timeout, a model that didn't come back with something usable).
 */
export async function fetchSessionAskHint(
  sessionId: string,
  init?: RequestInit,
): Promise<string> {
  try {
    const response = await apiFetch(
      apiUrl(`/api/sessions/${sessionId}/ask-hint`),
      { cache: "no-store", ...init },
    );
    const result = await expectJson<{ hint?: string }>(response);
    return typeof result.hint === "string" ? result.hint : "";
  } catch {
    // A missing hint is not a failure the composer should ever surface.
    return "";
  }
}

export async function updateSessionTitle(
  sessionId: string,
  title: string,
): Promise<SessionDetail> {
  const response = await apiFetch(apiUrl(`/api/sessions/${sessionId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await expectJson<{ session: SessionDetail }>(response);
  invalidateClientCache("sessions:");
  return data.session;
}

export async function getMessageTrace(
  sessionId: string,
  messageId: number,
  afterSeq = 0,
  signal?: AbortSignal,
): Promise<MessageTracePage> {
  const response = await apiFetch(
    apiUrl(
      `/api/sessions/${sessionId}/messages/${messageId}/events?after_seq=${afterSeq}&limit=500`,
    ),
    { cache: "no-store", signal },
  );
  return expectJson<MessageTracePage>(response);
}

export type SessionOrganizationPatch = Partial<{
  course_id: string;
  parent_session_id: string;
  session_kind: "chat" | "selection_tutor";
  pinned: boolean;
  archived: boolean;
}>;

export async function updateSessionOrganization(
  sessionId: string,
  patch: SessionOrganizationPatch,
): Promise<SessionDetail> {
  const response = await apiFetch(
    apiUrl(`/api/sessions/${sessionId}/organization`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  const data = await expectJson<{ session: SessionDetail }>(response);
  invalidateClientCache("sessions:");
  return data.session;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/sessions/${sessionId}`), {
    method: "DELETE",
  });
  await expectJson<{ deleted: boolean }>(response);
  invalidateClientCache("sessions:");
}

export async function recordQuizResults(
  sessionId: string,
  answers: QuizResultItem[],
  turnId?: string | null,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/sessions/${sessionId}/quiz-results`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers, turn_id: turnId || "" }),
    },
  );
  await expectJson<{ recorded: boolean }>(response);
}

export async function deleteMessage(
  sessionId: string,
  messageId: number,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/sessions/${sessionId}/messages/${messageId}`),
    { method: "DELETE" },
  );
  await expectJson<{ deleted: boolean }>(response);
}

export async function updateBranchSelection(
  sessionId: string,
  selectedBranches: Record<string, number>,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/sessions/${sessionId}/branch-selection`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_branches: selectedBranches }),
    },
  );
  await expectJson<{ selected_branches: Record<string, number> }>(response);
}
