/** Typed client for the /api/partners backend. */

import { apiFetch, apiUrl } from "@/lib/api";
import type { LLMSelection } from "@/features/chat/model/protocol";

export interface PartnerInfo {
  partner_id: string;
  name: string;
  description: string;
  /** Account that created the partner; empty for admin-managed ones. */
  owner_id?: string;
  /**
   * Whether the signed-in user may configure this partner (its owner, or an
   * admin). False for a partner merely assigned to them, whose response is
   * reduced to identity fields — so read this rather than re-deriving it.
   */
  can_manage?: boolean;
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
  /** Provider grouping key; `server` is its pre-provider spelling. */
  provider_id: string;
  server: string;
  /** `"mcp"` today, `"cli"` once CLI-app providers land. */
  kind: string;
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
  /** The platform conversation this session belongs to, when the channel said. */
  chat_id?: string;
  /** "group" or "direct"; absent when the channel does not distinguish them. */
  scope?: string;
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

export interface ConfirmPartnerDraftPayload {
  name?: string;
  description?: string;
  soul?: string;
  language?: string;
  emoji?: string;
  color?: string;
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
  return json(await apiFetch(apiUrl("/api/partners"), { cache: "no-store" }));
}

export async function getPartner(
  partnerId: string,
  options?: { includeSecrets?: boolean },
): Promise<PartnerInfo> {
  const query = options?.includeSecrets ? "?include_secrets=true" : "";
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}${query}`),
    ),
  );
}

export async function createPartner(
  payload: CreatePartnerPayload,
): Promise<PartnerInfo> {
  return json(
    await apiFetch(apiUrl("/api/partners"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function confirmPartnerDraft(
  draftId: string,
  payload: ConfirmPartnerDraftPayload,
): Promise<PartnerInfo> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/drafts/${encodeURIComponent(draftId)}/confirm`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function updatePartner(
  partnerId: string,
  payload: Partial<CreatePartnerPayload> & {
    channels?: Record<string, unknown>;
  },
): Promise<PartnerInfo> {
  return json(
    await apiFetch(apiUrl(`/api/partners/${encodeURIComponent(partnerId)}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function startPartner(partnerId: string): Promise<PartnerInfo> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/start`),
      { method: "POST" },
    ),
  );
}

export async function stopPartner(partnerId: string): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/stop`),
      { method: "POST" },
    ),
  );
}

export async function destroyPartner(partnerId: string): Promise<void> {
  await json(
    await apiFetch(apiUrl(`/api/partners/${encodeURIComponent(partnerId)}`), {
      method: "DELETE",
    }),
  );
}

export async function getPartnerSoul(partnerId: string): Promise<string> {
  const data = await json<{ content: string }>(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/soul`),
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
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/soul`),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  );
}

export async function getSoulSources(): Promise<SoulSources> {
  return json(await apiFetch(apiUrl("/api/partners/soul-sources")));
}

export async function createSoulTemplate(
  id: string,
  name: string,
  content: string,
): Promise<SoulTemplate> {
  return json(
    await apiFetch(apiUrl("/api/partners/souls"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name, content }),
    }),
  );
}

export async function getToolOptions(): Promise<ToolOptions> {
  return json(await apiFetch(apiUrl("/api/partners/tool-options")));
}

export async function getPartnerCommands(): Promise<PartnerCommandInfo[]> {
  const data = await json<{ commands: PartnerCommandInfo[] }>(
    await apiFetch(apiUrl("/api/partners/commands/palette")),
  );
  return data.commands;
}

export async function getPartnerAssets(
  partnerId: string,
): Promise<PartnerAssets> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/assets`),
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
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/assets`),
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
        `/api/partners/${encodeURIComponent(partnerId)}/assets/${assetType}/${encodeURIComponent(name)}`,
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

export interface PartnerChannelRuntimeSetup {
  status: string;
  message?: string;
  qr_payload?: string;
  qr_data_url?: string | null;
}

export interface PartnerChannelRuntimeEntry {
  enabled: boolean;
  running: boolean;
  setup: PartnerChannelRuntimeSetup;
}

export interface PartnerChannelRuntimeResponse {
  partner_id: string;
  running: boolean;
  channels: Record<string, PartnerChannelRuntimeEntry>;
}

export async function getPartnerChannelRuntime(
  partnerId: string,
): Promise<PartnerChannelRuntimeResponse> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/channels/status`),
      { cache: "no-store" },
    ),
  );
}

export type PartnerChannelOnboardingChannel = "feishu" | "wecom";

export type PartnerChannelOnboardingStatus =
  | "pending_scan"
  | "ready"
  | "applied"
  | "cancelled"
  | "expired"
  | "denied"
  | "failed";

export interface PartnerChannelOnboardingSession {
  session_id: string;
  partner_id: string;
  channel: PartnerChannelOnboardingChannel;
  status: PartnerChannelOnboardingStatus;
  qr_payload: string;
  qr_data_url: string | null;
  fallback_url: string;
  poll_interval_seconds: number;
  expires_at: string;
  error_code?: string;
}

export function supportsChannelOnboarding(
  channel: string,
  available: boolean | undefined,
): boolean {
  return available !== false && (channel === "feishu" || channel === "wecom");
}

export async function startChannelOnboarding(
  partnerId: string,
  channel: PartnerChannelOnboardingChannel,
): Promise<PartnerChannelOnboardingSession> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channel-onboarding/start`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel }),
      },
    ),
  );
}

export async function getChannelOnboarding(
  partnerId: string,
  sessionId: string,
): Promise<PartnerChannelOnboardingSession> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channel-onboarding/${encodeURIComponent(sessionId)}`,
      ),
      { cache: "no-store" },
    ),
  );
}

export async function cancelChannelOnboarding(
  partnerId: string,
  sessionId: string,
): Promise<PartnerChannelOnboardingSession> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channel-onboarding/${encodeURIComponent(sessionId)}`,
      ),
      { method: "DELETE" },
    ),
  );
}

export async function applyChannelOnboarding(
  partnerId: string,
  sessionId: string,
): Promise<{ session: PartnerChannelOnboardingSession }> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channel-onboarding/${encodeURIComponent(sessionId)}/apply`,
      ),
      { method: "POST" },
    ),
  );
}

export async function getChannelSchemas(): Promise<ChannelsSchemaResponse> {
  // no-store: availability reflects live server imports (e.g. a dependency
  // installed minutes ago) — a cached copy here shows phantom-missing channels.
  return json(
    await apiFetch(apiUrl("/api/partners/channels/schema"), {
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
    sender_id?: string;
    metadata?: Record<string, unknown>;
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
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/history${query}`),
    ),
  );
}

export async function getPartnerSessions(
  partnerId: string,
): Promise<PartnerSessionInfo[]> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/sessions`),
      { cache: "no-store" },
    ),
  );
}

async function postSessionAction(
  partnerId: string,
  action: "archive" | "resume" | "delete",
  sessionKey: string,
): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/sessions/${action}`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_key: sessionKey }),
      },
    ),
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
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/sessions/branch`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_key: sourceKey, new_key: newKey }),
      },
    ),
  );
}

// ── Channel account links ─────────────────────────────────────
//
// Connecting a chat account (QQ, Telegram, …) to your DeepTutor account, so
// messages you send the partner there are yours: private history you can read
// back here, answered out of your own library and memory.

export interface PartnerLink {
  key: string;
  channel: string;
  sender_id: string;
  linked_at: string;
}

export interface PartnerLinkCode {
  code: string;
  expires_at: string;
  /** Ready-to-send command, e.g. "/link A1B2C3". */
  command: string;
}

export async function createPartnerLinkCode(
  partnerId: string,
): Promise<PartnerLinkCode> {
  return json(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/links/code`),
      { method: "POST" },
    ),
  );
}

export async function listPartnerLinks(
  partnerId: string,
): Promise<PartnerLink[]> {
  const data = await json<{ links: PartnerLink[] }>(
    await apiFetch(
      apiUrl(`/api/partners/${encodeURIComponent(partnerId)}/links`),
    ),
  );
  return data.links ?? [];
}

export async function removePartnerLink(
  partnerId: string,
  key: string,
): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/links/${encodeURIComponent(key)}`,
      ),
      { method: "DELETE" },
    ),
  );
}

// ── WeChat QR onboarding (#951) ───────────────────────────────────────────────
//
// The personal-WeChat channel authenticates by scanning a QR code. The channel
// has always known how to run that exchange, but drew the code on the server's
// stdout — unreachable on a container deployment — so these drive it from the
// browser instead. The bot token is written into the partner's channel config
// server-side; nothing here ever sees it.

export interface WeixinQrSession {
  session_id: string;
  /** waiting | scanned | confirmed | expired | error */
  status: string;
  error: string;
  expires_in: number;
  /** What the phone scans. Present on start, and again whenever it changes. */
  scan_payload?: string;
  /** Inline SVG of `scan_payload`, rendered server-side (no QR lib in the web
   *  bundle). Absent when unchanged since the last reply, or when the server
   *  lacks the `qrcode` library — fall back to showing `scan_payload`. */
  qr_svg?: string;
}

export async function startWeixinQr(
  partnerId: string,
): Promise<WeixinQrSession> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channels/weixin/qr`,
      ),
      { method: "POST" },
    ),
  );
}

export async function pollWeixinQr(
  partnerId: string,
  sessionId: string,
): Promise<WeixinQrSession> {
  return json(
    await apiFetch(
      apiUrl(
        `/api/partners/${encodeURIComponent(partnerId)}/channels/weixin/qr/${encodeURIComponent(sessionId)}`,
      ),
      { cache: "no-store" },
    ),
  );
}
