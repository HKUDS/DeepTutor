/** Typed client for the /api/v1/partners backend. */

import { apiFetch, apiUrl } from "@/lib/api";
import type { LLMSelection } from "@/lib/unified-ws";

export interface PartnerInfo {
  partner_id: string;
  name: string;
  description: string;
  /** List endpoints: channel name keys only. Detail: full (masked) dict. */
  channels: string[] | Record<string, unknown>;
  llm_selection?: LLMSelection | null;
  backup_llm_selection?: LLMSelection | null;
  model?: string | null;
  language?: string;
  emoji?: string;
  color?: string;
  avatar?: string;
  soul_origin?: { type?: string; id?: string };
  enabled_tools?: string[] | null;
  builtin_tools?: string[] | null;
  mcp_tools?: string[] | null;
  running: boolean;
  started_at: string | null;
  last_reload_error?: string | null;
  provisioning?: ProvisioningReport;
  start_error?: string;
}

export interface ProvisioningReport {
  copied: Record<string, string[]>;
  errors: { type: string; name: string; error: string }[];
}

export interface SoulTemplate {
  id: string;
  name: string;
  content: string;
}

export interface SoulSources {
  library: SoulTemplate[];
  personas: { name: string; description: string; content?: string }[];
}

export interface ToolOption {
  name: string;
  description: string;
}

export interface McpToolOption extends ToolOption {
  server: string;
}

export interface ToolOptions {
  tools: ToolOption[];
  /** Auto-mounted built-in tools an owner may allow/deny (default: all). */
  builtin_tools: ToolOption[];
  mcp_tools: McpToolOption[];
}

export interface PartnerAssets {
  knowledge_bases: { name: string; documents?: number }[];
  skills: { name: string }[];
  notebooks: { id: string; name: string; record_count?: number }[];
}

export interface PartnerSessionInfo {
  session_key: string;
  /** Opening user message, trimmed — the conversation's human label. */
  title?: string;
  message_count: number;
  updated_at: string;
  last_message: string;
  archived?: boolean;
}

export interface PartnerCommandInfo {
  command: string;
  description: string;
  arg_hint?: string;
}

export interface SoulSpec {
  source: "default" | "library" | "persona" | "custom";
  id?: string;
  content?: string;
}

export interface CreatePartnerPayload {
  partner_id?: string;
  name: string;
  description?: string;
  soul?: SoulSpec;
  channels?: Record<string, unknown>;
  llm_selection?: LLMSelection | null;
  backup_llm_selection?: LLMSelection | null;
  language?: string;
  emoji?: string;
  color?: string;
  avatar?: string;
  enabled_tools?: string[] | null;
  builtin_tools?: string[] | null;
  mcp_tools?: string[] | null;
  assets?: {
    knowledge_bases?: string[];
    skills?: string[];
    notebooks?: string[];
  };
  start?: boolean;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: string | { message?: string };
    };
    const detail = body.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : (detail?.message ?? `Request failed: ${res.status}`);
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export async function listPartners(): Promise<PartnerInfo[]> {
  return json(
    await apiFetch(apiUrl("/api/v1/partners"), { cache: "no-store" }),
  );
}

export async function getPartner(
  partnerId: string,
  options?: { includeSecrets?: boolean },
): Promise<PartnerInfo> {
  const query = options?.includeSecrets ? "?include_secrets=true" : "";
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}${query}`),
    ),
  );
}

export async function createPartner(
  payload: CreatePartnerPayload,
): Promise<PartnerInfo> {
  return json(
    await apiFetch(apiUrl("/api/v1/partners"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function updatePartner(
  partnerId: string,
  payload: Partial<CreatePartnerPayload> & {
    channels?: Record<string, unknown>;
  },
): Promise<PartnerInfo> {
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}`),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function startPartner(partnerId: string): Promise<PartnerInfo> {
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/start`),
      { method: "POST" },
    ),
  );
}

export async function stopPartner(partnerId: string): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/stop`),
      { method: "POST" },
    ),
  );
}

export async function destroyPartner(partnerId: string): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}`),
      {
        method: "DELETE",
      },
    ),
  );
}

export async function getPartnerSoul(partnerId: string): Promise<string> {
  const data = await json<{ content: string }>(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/soul`),
    ),
  );
  return data.content ?? "";
}

export async function savePartnerSoul(
  partnerId: string,
  content: string,
): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/soul`),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  );
}

export async function getSoulSources(): Promise<SoulSources> {
  return json(await apiFetch(apiUrl("/api/v1/partners/soul-sources")));
}

export async function createSoulTemplate(
  id: string,
  name: string,
  content: string,
): Promise<SoulTemplate> {
  return json(
    await apiFetch(apiUrl("/api/v1/partners/souls"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name, content }),
    }),
  );
}

export async function getToolOptions(): Promise<ToolOptions> {
  return json(await apiFetch(apiUrl("/api/v1/partners/tool-options")));
}

export async function getPartnerCommands(): Promise<PartnerCommandInfo[]> {
  const data = await json<{ commands: PartnerCommandInfo[] }>(
    await apiFetch(apiUrl("/api/v1/partners/commands/palette")),
  );
  return data.commands;
}

export async function getPartnerAssets(
  partnerId: string,
): Promise<PartnerAssets> {
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/assets`),
    ),
  );
}

export async function addPartnerAssets(
  partnerId: string,
  assets: {
    knowledge_bases?: string[];
    skills?: string[];
    notebooks?: string[];
  },
): Promise<{ assets: PartnerAssets } & ProvisioningReport> {
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/assets`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(assets),
      },
    ),
  );
}

export async function removePartnerAsset(
  partnerId: string,
  assetType: "knowledge_base" | "skill" | "notebook",
  name: string,
): Promise<{ assets: PartnerAssets }> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/v1/partners/${encodeURIComponent(partnerId)}/assets/${assetType}/${encodeURIComponent(name)}`,
      ),
      { method: "DELETE" },
    ),
  );
}

export interface ChannelSchemaEntry {
  name: string;
  display_name: string;
  default_config: Record<string, unknown>;
  secret_fields: string[];
  // null when the channel module failed to import (missing optional
  // dependency); `unavailable_reason` then carries the import error.
  json_schema: Record<string, unknown> | null;
  available?: boolean;
  unavailable_reason?: string;
}

export interface ChannelsSchemaResponse {
  channels: Record<string, ChannelSchemaEntry>;
}

export async function getChannelSchemas(): Promise<ChannelsSchemaResponse> {
  // no-store: availability reflects live server imports (e.g. a dependency
  // installed minutes ago) — a cached copy here shows phantom-missing channels.
  return json(
    await apiFetch(apiUrl("/api/v1/partners/channels/schema"), {
      cache: "no-store",
    }),
  );
}

export async function getPartnerHistory(
  partnerId: string,
  options?: { sessionKey?: string; sessionId?: string; limit?: number },
): Promise<
  {
    role: string;
    content: string;
    timestamp?: string;
    channel?: string;
    attachments?: Record<string, unknown>[];
    /** Persisted turn trace (assistant rows only) for rehydrating activity. */
    events?: Record<string, unknown>[];
  }[]
> {
  const params = new URLSearchParams();
  if (options?.sessionKey) params.set("session_key", options.sessionKey);
  if (options?.sessionId) params.set("session_id", options.sessionId);
  if (options?.limit) params.set("limit", String(options.limit));
  const query = params.toString() ? `?${params.toString()}` : "";
  return json(
    await apiFetch(
      apiUrl(
        `/api/v1/partners/${encodeURIComponent(partnerId)}/history${query}`,
      ),
    ),
  );
}

export async function getPartnerSessions(
  partnerId: string,
): Promise<PartnerSessionInfo[]> {
  return json(
    await apiFetch(
      apiUrl(`/api/v1/partners/${encodeURIComponent(partnerId)}/sessions`),
      { cache: "no-store" },
    ),
  );
}

async function postSessionAction(
  partnerId: string,
  action: "archive" | "resume" | "delete",
  sessionKey: string,
): Promise<void> {
  await apiFetch(
    apiUrl(
      `/api/v1/partners/${encodeURIComponent(partnerId)}/sessions/${action}`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_key: sessionKey }),
    },
  );
}

export function archivePartnerSession(partnerId: string, sessionKey: string) {
  return postSessionAction(partnerId, "archive", sessionKey);
}

export function resumePartnerSession(partnerId: string, sessionKey: string) {
  return postSessionAction(partnerId, "resume", sessionKey);
}

export function deletePartnerSession(partnerId: string, sessionKey: string) {
  return postSessionAction(partnerId, "delete", sessionKey);
}

export async function branchPartnerSession(
  partnerId: string,
  sourceKey: string,
  newKey: string,
): Promise<{ session: PartnerSessionInfo }> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/v1/partners/${encodeURIComponent(partnerId)}/sessions/branch`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_key: sourceKey, new_key: newKey }),
      },
    ),
  );
}
