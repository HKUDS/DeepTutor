import { apiFetch, apiUrl } from "@/lib/api";

export type CodeBuddyAuthStatus = {
  connection: "disconnected" | "authorizing" | "connected" | "error";
  operation_state: "waiting" | "completed" | "cancelled" | "failed" | null;
  authorize_url: string | null;
  user_label: string | null;
  error_code: string | null;
};

const BASE = "/api/v1/settings/providers/codebuddy/auth";

async function request(
  path: string,
  method: "GET" | "POST",
): Promise<CodeBuddyAuthStatus> {
  const response = await apiFetch(apiUrl(`${BASE}${path}`), {
    method,
    skipAuthRedirect: true,
  });
  if (!response.ok) {
    throw new Error(`CodeBuddy auth request failed: HTTP ${response.status}`);
  }
  return (await response.json()) as CodeBuddyAuthStatus;
}

export function getCodeBuddyAuthStatus(): Promise<CodeBuddyAuthStatus> {
  return request("/status", "GET");
}

export function startCodeBuddyLogin(): Promise<CodeBuddyAuthStatus> {
  return request("/start", "POST");
}

export function cancelCodeBuddyLogin(): Promise<CodeBuddyAuthStatus> {
  return request("/cancel", "POST");
}

export function logoutCodeBuddy(): Promise<CodeBuddyAuthStatus> {
  return request("/logout", "POST");
}

export function shouldPollCodeBuddyAuth(status: CodeBuddyAuthStatus): boolean {
  return status.operation_state === "waiting";
}
