import { apiFetch, apiUrl } from "@/lib/api";

export type McpTransport = "stdio" | "sse" | "streamableHttp";

export type McpServerStatus = "connecting" | "connected" | "error" | "disabled";

export interface McpServerConfig {
  type: McpTransport | null;
  // stdio transport
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  // http transports
  url: string;
  headers: Record<string, string>;
  // behaviour
  tool_timeout: number;
  enabled_tools: string[];
  enabled: boolean;
}

export interface McpTool {
  name: string;
  description: string;
}

export interface McpStatusRow {
  name: string;
  transport: string;
  status: McpServerStatus;
  error: string;
  tools: McpTool[];
}

export interface McpSettings {
  servers: Record<string, McpServerConfig>;
  status: McpStatusRow[];
}

export interface McpTestResult {
  ok: boolean;
  tools: McpTool[];
  error: string;
}

const MCP_SETTINGS_PATH = "/api/v1/settings/mcp";

export function emptyMcpServerConfig(): McpServerConfig {
  return {
    type: null,
    command: "",
    args: [],
    env: {},
    cwd: "",
    url: "",
    headers: {},
    tool_timeout: 30,
    enabled_tools: ["*"],
    enabled: true,
  };
}

async function asJson(response: Response) {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

function normalizeTool(raw: unknown): McpTool {
  const item = (raw ?? {}) as { name?: unknown; description?: unknown };
  return {
    name: String(item.name ?? ""),
    description: String(item.description ?? ""),
  };
}

function normalizeStatusRow(raw: unknown): McpStatusRow {
  const item = (raw ?? {}) as {
    name?: unknown;
    transport?: unknown;
    status?: unknown;
    error?: unknown;
    tools?: unknown;
  };
  const status = String(item.status ?? "");
  const known: McpServerStatus[] = [
    "connecting",
    "connected",
    "error",
    "disabled",
  ];
  return {
    name: String(item.name ?? ""),
    transport: String(item.transport ?? ""),
    status: (known.includes(status as McpServerStatus)
      ? status
      : "error") as McpServerStatus,
    error: String(item.error ?? ""),
    tools: Array.isArray(item.tools) ? item.tools.map(normalizeTool) : [],
  };
}

function normalizeServerConfig(raw: unknown): McpServerConfig {
  const base = emptyMcpServerConfig();
  const item = (raw ?? {}) as Record<string, unknown>;
  const type = item.type;
  return {
    ...base,
    type:
      type === "stdio" || type === "sse" || type === "streamableHttp"
        ? type
        : null,
    command: String(item.command ?? base.command),
    args: Array.isArray(item.args)
      ? item.args.map((a) => String(a))
      : base.args,
    env: normalizeStringMap(item.env),
    cwd: String(item.cwd ?? base.cwd),
    url: String(item.url ?? base.url),
    headers: normalizeStringMap(item.headers),
    tool_timeout:
      typeof item.tool_timeout === "number" &&
      Number.isFinite(item.tool_timeout)
        ? item.tool_timeout
        : base.tool_timeout,
    enabled_tools: Array.isArray(item.enabled_tools)
      ? item.enabled_tools.map((a) => String(a))
      : base.enabled_tools,
    enabled: item.enabled === undefined ? base.enabled : Boolean(item.enabled),
  };
}

function normalizeStringMap(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    out[key] = String(value ?? "");
  }
  return out;
}

function normalizeServers(raw: unknown): Record<string, McpServerConfig> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, McpServerConfig> = {};
  for (const [name, cfg] of Object.entries(raw as Record<string, unknown>)) {
    out[name] = normalizeServerConfig(cfg);
  }
  return out;
}

export async function getMcpSettings(): Promise<McpSettings> {
  const response = await apiFetch(apiUrl(MCP_SETTINGS_PATH), {
    cache: "no-store",
  });
  const data = await asJson(response);
  return {
    servers: normalizeServers(data?.servers),
    status: Array.isArray(data?.status)
      ? data.status.map(normalizeStatusRow)
      : [],
  };
}

export async function updateMcpSettings(
  servers: Record<string, McpServerConfig>,
): Promise<McpStatusRow[]> {
  const response = await apiFetch(apiUrl(MCP_SETTINGS_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ servers }),
  });
  const data = await asJson(response);
  return Array.isArray(data?.status) ? data.status.map(normalizeStatusRow) : [];
}

export async function testMcpServer(
  cfg: McpServerConfig,
): Promise<McpTestResult> {
  const response = await apiFetch(apiUrl(`${MCP_SETTINGS_PATH}/test`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const data = await asJson(response);
  return {
    ok: Boolean(data?.ok),
    tools: Array.isArray(data?.tools) ? data.tools.map(normalizeTool) : [],
    error: String(data?.error ?? ""),
  };
}
