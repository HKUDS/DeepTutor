import type { components } from "@/contracts/generated/api";
import { apiFetch, apiUrl } from "@/lib/api";

export type GitHubCopilotAuthStatus =
  components["schemas"]["GitHubCopilotAuthStatusResponse"];

const BASE = "/api/settings/providers/github-copilot/auth";

async function request(
  path: string,
  method: "GET" | "POST",
  signal?: AbortSignal,
): Promise<GitHubCopilotAuthStatus> {
  const response = await apiFetch(apiUrl(`${BASE}${path}`), {
    method,
    signal,
    skipAuthRedirect: true,
  });
  if (!response.ok) {
    throw new Error(
      `GitHub Copilot auth request failed: HTTP ${response.status}`,
    );
  }
  return (await response.json()) as GitHubCopilotAuthStatus;
}

export function getGitHubCopilotAuthStatus(
  signal?: AbortSignal,
): Promise<GitHubCopilotAuthStatus> {
  return request("/status", "GET", signal);
}

export function startGitHubCopilotLogin(): Promise<GitHubCopilotAuthStatus> {
  return request("/start", "POST");
}

export function cancelGitHubCopilotLogin(): Promise<GitHubCopilotAuthStatus> {
  return request("/cancel", "POST");
}

export function logoutGitHubCopilot(): Promise<GitHubCopilotAuthStatus> {
  return request("/logout", "POST");
}

export function shouldPollGitHubCopilotAuth(
  status: GitHubCopilotAuthStatus,
): boolean {
  return status.connection === "authorizing" && status.operation_state === "waiting";
}
