import type { StreamEvent } from "@/lib/unified-ws";
import { apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

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
  }>;
  created_at: number;
}

export interface SessionSummary {
  id: string;
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  last_message: string;
  status?: "idle" | "running" | "completed" | "failed" | "cancelled" | "rejected";
  active_turn_id?: string;
  preferences?: {
    capability?: string;
    tools?: string[];
    knowledge_bases?: string[];
    language?: string;
  };
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
  status?: "idle" | "running" | "completed" | "failed" | "cancelled" | "rejected";
  active_turn_id?: string;
  compressed_summary?: string;
  summary_up_to_msg_id?: number;
  preferences?: {
    capability?: string;
    tools?: string[];
    knowledge_bases?: string[];
    language?: string;
  };
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
  return withClientCache<SessionSummary[]>(
    `sessions:${limit}:${offset}`,
    async () => {
      const response = await fetch(apiUrl(`/api/v1/sessions?limit=${limit}&offset=${offset}`), {
        cache: "no-store",
      });
      const data = await expectJson<{ sessions: SessionSummary[] }>(response);
      return data.sessions ?? [];
    },
    {
      force: options?.force,
      ttlMs: 15_000,
    },
  );
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    cache: "no-store",
  });
  return expectJson<SessionDetail>(response);
}

export async function updateSessionTitle(sessionId: string, title: string): Promise<SessionDetail> {
  const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await expectJson<{ session: SessionDetail }>(response);
  invalidateClientCache("sessions:");
  return data.session;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    method: "DELETE",
  });
  await expectJson<{ deleted: boolean }>(response);
  invalidateClientCache("sessions:");
}

export async function recordQuizResults(
  sessionId: string,
  answers: QuizResultItem[],
): Promise<void> {
  const response = await fetch(apiUrl(`/api/v1/sessions/${sessionId}/quiz-results`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });
  await expectJson<{ recorded: boolean }>(response);
}
