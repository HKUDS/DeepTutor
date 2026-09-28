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
  ui: "/api/settings/ui",
  tools: "/api/settings/enabled-tools",
  workspace: "/api/settings/workspace",
  "video-learning": "/api/settings/video-learning",
  "learner-profile": "/api/auth/profile/learner-profile",
  "document-parsing": "/api/settings/document-parsing",
  mineru: "/api/settings/mineru",
  "update-checks": "/api/system/update/settings",
  "chat-starters": "/api/settings/chat-starters",
  "chat-attachments": "/api/settings/chat-attachments",
  "chat-timeout": "/api/settings/chat-response-timeout",
  capabilities: "/api/capabilities/settings",
  memory: "/api/memory/settings",
  network: "/api/settings/network",
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
  if (payload == null) throw new Error(`Missing settings payload: ${key}`);
  if (key === "codex-reasoning") {
    const { setCodexReasoningEffort } = await import("@/lib/codex-oauth");
    for (const [model, effort] of Object.entries(payload as Record<string, string | null>)) {
      await setCodexReasoningEffort(model, effort);
    }
    return;
  }
  if (key.startsWith("subagent:")) {
    const { updateSubagentSettings } = await import("@/lib/subagents-api");
    await updateSubagentSettings({ backends: { [key.slice(9)]: payload } });
    return;
  }
  const guardian = /^guardian:(materials|restrictions):(.+)$/.exec(key);
  const endpoint = guardian
    ? `/api/multi-user/learners/${encodeURIComponent(guardian[2])}/${guardian[1]}`
    : isExtensionKey(key) ? EXTENSION_ENDPOINTS[key] : null;
  if (!endpoint) throw new Error(`Unknown settings section: ${key}`);
  let body = guardian?.[1] === "materials" ? { book_ids: payload } : payload;
  if (key === "document-parsing") {
    const { engine, engines } = payload as { engine: string; engines: Record<string, unknown> };
    // MinerU has its own draft; never overwrite it with this page's snapshot.
    body = { engine, engines: Object.fromEntries(Object.entries(engines).filter(([name]) => name !== "mineru")) };
  }
  const response = await apiFetch(apiUrl(endpoint), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(`${key}: ${typeof error.detail === "string" ? error.detail : `HTTP ${response.status}`}`);
  }
  if (key === "tools") {
    const { invalidateEnabledOptionalToolsCache } = await import("@/lib/tools-settings");
    invalidateEnabledOptionalToolsCache();
  }
}
