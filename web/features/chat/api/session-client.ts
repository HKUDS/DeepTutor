import { requestJson, requestVoid } from "@/shared/api/client";

export interface SessionWireMessage {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  parent_message_id?: number | null;
  capability?: string;
  events?: unknown[];
}

export interface SessionWireDetail {
  id?: string;
  session_id?: string;
  title: string;
  status?: string;
  active_turn_id?: string | null;
  messages: SessionWireMessage[];
  preferences?: Record<string, unknown>;
  updated_at?: number;
}

export interface SessionClient {
  get(sessionId: string, signal?: AbortSignal): Promise<SessionWireDetail>;
  rename(sessionId: string, title: string): Promise<SessionWireDetail>;
  remove(sessionId: string): Promise<void>;
  selectBranch(
    sessionId: string,
    selectedBranches: Record<string, number>,
  ): Promise<void>;
  removeMessage(sessionId: string, messageId: number): Promise<void>;
}

function id(value: string): string {
  return encodeURIComponent(value);
}

export const sessionClient: SessionClient = {
  get(sessionId, signal) {
    return requestJson<SessionWireDetail>(`/api/sessions/${id(sessionId)}`, {
      cache: "no-store",
      signal,
      scope: "session",
    });
  },
  async rename(sessionId, title) {
    const result = await requestJson<
      SessionWireDetail | { session: SessionWireDetail }
    >(`/api/sessions/${id(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
      scope: "session",
    });
    return "session" in result ? result.session : result;
  },
  remove(sessionId) {
    return requestVoid(`/api/sessions/${id(sessionId)}`, {
      method: "DELETE",
      scope: "session",
    });
  },
  selectBranch(sessionId, selectedBranches) {
    return requestVoid(`/api/sessions/${id(sessionId)}/branch-selection`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_branches: selectedBranches }),
      scope: "session",
    });
  },
  removeMessage(sessionId, messageId) {
    return requestVoid(`/api/sessions/${id(sessionId)}/messages/${messageId}`, {
      method: "DELETE",
      scope: "session",
    });
  },
};
