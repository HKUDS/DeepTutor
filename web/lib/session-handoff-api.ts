import { apiFetch, apiUrl } from "@/lib/api";

export interface SessionHandoff {
  code: string;
  handoff_url: string;
  expires_at: number;
  expires_in: number;
}

export async function createSessionHandoff(
  publicOrigin: string,
): Promise<SessionHandoff> {
  const response = await apiFetch(apiUrl("/api/auth/session-handoff"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ public_origin: publicOrigin }),
    skipAuthRedirect: true,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(String(body.detail ?? "Could not create pairing link"));
  }
  return body as SessionHandoff;
}

export async function exchangeSessionHandoff(code: string): Promise<string> {
  const response = await apiFetch(apiUrl("/api/auth/session-handoff/exchange"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
    skipAuthRedirect: true,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(String(body.detail ?? "Pairing code is invalid"));
  }
  return String(body.ticket);
}

export async function completeSessionHandoff(ticket: string): Promise<void> {
  const response = await apiFetch(apiUrl("/api/auth/session-handoff/complete"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket }),
    skipAuthRedirect: true,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(String(body.detail ?? "Pairing could not be completed"));
  }
}
