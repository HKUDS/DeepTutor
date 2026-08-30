import { apiFetch, apiUrl } from "@/lib/api";

/**
 * Settings pages that keep state outside the model catalog.
 *
 * Each one registers with `registerExtension(key, …)` under the key below and
 * saves by PUT-ing its own payload to the matching endpoint. The table exists
 * so a draft can be applied for a page that is not on screen: the user edits
 * Starting points, navigates to LLM, and presses Apply — nothing is mounted to
 * run that page's own save closure any more, but its drafted payload is still
 * pending and has to land somewhere.
 *
 * The pages import their URL from here rather than writing it twice, so the
 * two paths cannot drift apart.
 */
export const EXTENSION_ENDPOINTS = {
  "chat-starters": "/api/v1/settings/chat-starters",
  "chat-attachments": "/api/v1/settings/chat-attachments",
  "chat-timeout": "/api/v1/settings/chat-response-timeout",
  capabilities: "/api/v1/capabilities/settings",
  memory: "/api/v1/memory/settings",
  network: "/api/v1/settings/network",
} as const;

export type ExtensionKey = keyof typeof EXTENSION_ENDPOINTS;

export function isExtensionKey(value: string): value is ExtensionKey {
  return value in EXTENSION_ENDPOINTS;
}

/** Write one drafted payload to the endpoint that owns it. */
export async function applyExtensionPayload(
  key: string,
  payload: unknown,
): Promise<void> {
  if (!isExtensionKey(key) || payload == null) return;
  const response = await apiFetch(apiUrl(EXTENSION_ENDPOINTS[key]), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`${key}: HTTP ${response.status}`);
  }
}
