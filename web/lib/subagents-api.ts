import { apiFetch, apiUrl } from "@/lib/api";

/** One agent CLI backend's installability on this machine. */
export interface SubagentBackendInfo {
  kind: string;
  display_name: string;
  available: boolean;
  version: string;
  detail: string;
}

/** A connected subagent the user can consult in chat. */
export interface SubagentConnection {
  name: string;
  agent_kind: string;
  cwd: string;
  /** Set for a partner connection (`agent_kind === "partner"`): the bound partner. */
  partner_id?: string;
  description?: string;
  created_at?: string;
  updated_at?: string | null;
}

/**
 * A partner the current user may connect & consult. Admins get every partner;
 * non-admins get only the partners an admin has assigned to them. Identity-only
 * (no channel wiring / model selection) — that's what the connect flow needs.
 */
export interface ConnectablePartner {
  partner_id: string;
  name: string;
  description?: string;
  emoji?: string;
  color?: string;
  avatar?: string;
  language?: string;
  running?: boolean;
}

export async function listConnectablePartners(): Promise<ConnectablePartner[]> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/partners"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const data = (await res.json()) as { partners: ConnectablePartner[] };
  return data.partners ?? [];
}

export async function detectSubagents(): Promise<SubagentBackendInfo[]> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/detect"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Detect failed: ${res.status}`);
  const data = (await res.json()) as { backends: SubagentBackendInfo[] };
  return data.backends ?? [];
}

export async function listSubagentConnections(): Promise<SubagentConnection[]> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/connections"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const data = (await res.json()) as { connections: SubagentConnection[] };
  return data.connections ?? [];
}

export async function connectSubagent(payload: {
  name: string;
  agent_kind: string;
  cwd?: string;
  /** Required when `agent_kind === "partner"`: which partner to consult. */
  partner_id?: string;
}): Promise<SubagentConnection> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/connections"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d) => (d as { detail?: string }).detail)
      .catch(() => "");
    throw new Error(detail || `Connect failed: ${res.status}`);
  }
  return (await res.json()) as SubagentConnection;
}

export async function disconnectSubagent(name: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/subagents/connections/${encodeURIComponent(name)}`),
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Disconnect failed: ${res.status}`);
}

export interface SubagentModelOption {
  slug: string;
  display_name: string;
  default_effort: string;
  efforts: string[];
}

export interface SubagentBackendOptions {
  kind: string;
  display_name: string;
  available: boolean;
  version: string;
  default_model: string;
  models: SubagentModelOption[];
  efforts: string[];
  allow_custom_model: boolean;
  synced_at: string;
  detail: string;
}

export async function getBackendOptions(): Promise<SubagentBackendOptions[]> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/backends/options"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const data = (await res.json()) as { backends: SubagentBackendOptions[] };
  return data.backends ?? [];
}

/**
 * Re-pull one backend's model catalog (the settings "sync" button). For Claude
 * Code this scrapes its `/model` TUI live (can take a few seconds); for Codex it
 * re-reads the CLI's cache.
 */
export async function syncBackendOptions(
  kind: string,
): Promise<SubagentBackendOptions> {
  const res = await apiFetch(
    apiUrl(`/api/v1/subagents/backends/${encodeURIComponent(kind)}/sync`),
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`Sync failed: ${res.status}`);
  return (await res.json()) as SubagentBackendOptions;
}

export interface SubagentBackendConfig {
  enabled?: boolean;
  model?: string;
  effort?: string;
  system_prompt?: string;
  permission_mode?: string;
  sandbox?: string;
  approval?: string;
  network_access?: boolean;
  ephemeral?: boolean;
  forward_images?: boolean;
  extra_args?: string[];
}

export interface SubagentSettings {
  consult_budget: number;
  backends: Record<string, SubagentBackendConfig>;
}

/** One streamed line from the "message the agent directly" endpoint. */
export interface SubagentStreamLine {
  channel?: string;
  text?: string;
  merge_id?: string;
  done?: boolean;
  success?: boolean;
  session_id?: string;
}

/**
 * Send a message straight to a connected subagent and stream its run as
 * newline-delimited JSON. Resumes the same live session DeepTutor consults
 * (shared via the cross-turn registry), so the agent keeps context.
 */
export async function* streamSubagentMessage(
  name: string,
  body: { chat_session_id: string; message: string },
  signal?: AbortSignal,
): AsyncGenerator<SubagentStreamLine> {
  const res = await apiFetch(
    apiUrl(`/api/v1/subagents/connections/${encodeURIComponent(name)}/message`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!res.ok || !res.body) throw new Error(`Message failed: ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = function* (chunk: string): Generator<SubagentStreamLine> {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield JSON.parse(line) as SubagentStreamLine;
    }
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    yield* flush(decoder.decode(value, { stream: true }));
  }
  const tail = buf.trim();
  if (tail) yield JSON.parse(tail) as SubagentStreamLine;
}

export async function getSubagentSettings(): Promise<SubagentSettings> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/settings"), {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return (await res.json()) as SubagentSettings;
}

export async function updateSubagentSettings(
  payload: Partial<SubagentSettings>,
): Promise<SubagentSettings> {
  const res = await apiFetch(apiUrl("/api/v1/subagents/settings"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Update failed: ${res.status}`);
  return (await res.json()) as SubagentSettings;
}
