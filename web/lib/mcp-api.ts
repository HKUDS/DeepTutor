import { apiFetch, apiUrl } from "@/lib/api";

export type McpTransport = "stdio" | "sse" | "streamableHttp";

export type McpServerStatus =
  | "connecting"
  | "connected"
  | "error"
  // Waiting on a person to grant an OAuth authorization. Distinct from `error`
  // because the fix is a button, not a retry.
  | "needs_auth"
  | "disabled";

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
  // Blocklist applied after `enabled_tools` (mirrors MCPServerConfig on the
  // backend). No editor exposes it, so every write must carry the stored value
  // through: an absent field makes the backend fall back to its `[]` default,
  // which silently drops a hand-written blocklist.
  disabled_tools: string[];
  enabled: boolean;
  /**
   * `"oauth"` when this server needs an authorization the account grants in a
   * browser rather than a credential typed into the form. Read-only from the
   * client's side: it comes from the catalog entry.
   */
  auth: "" | "oauth";
  /**
   * Catalog entry this server was installed from, or `""` for a hand-written
   * one. Read-only provenance: no editor sets it, and every write carries the
   * stored value through so a save from the form does not erase it.
   */
  catalog_entry: string;
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

/** A stored entry the backend refuses to connect, and why. */
export interface McpRejectedServer {
  name: string;
  reason: string;
}

/**
 * Everything the per-user response adds on top of the shared
 * `servers` + `status` shape (see `deeptutor/api/routers/space_mcp.py`).
 */
export interface McpUserView {
  /**
   * Server name → the credential fields that have a stored value. The values
   * themselves never leave the backend, so this is only ever a "configured"
   * marker.
   */
  configuredSecrets: Record<string, string[]>;
  rejected: McpRejectedServer[];
  /** The deployment's servers, read-only: this account cannot edit them. */
  deployment: { servers: string[]; status: McpStatusRow[] };
  /** Per-account server cap; 0 when the backend did not report one. */
  maxServers: number;
  /**
   * Server name → whether this account has granted its OAuth authorization.
   * Only OAuth-backed servers appear. Presence only: a token never leaves the
   * backend.
   */
  oauth: Record<string, { required: boolean; authorized: boolean }>;
}

export interface McpStoreState extends McpSettings {
  /** Null on the admin registry, which has none of the per-user extras. */
  user: McpUserView | null;
}

/** Deployment-global registry (admin-gated). */
export const MCP_ADMIN_BASE_PATH = "/api/v1/settings/mcp";

/** The caller's own servers (auth-gated, remote transports only). */
export const MCP_SPACE_BASE_PATH = "/api/v1/space/mcp";

/** Every transport the connection manager can open. */
export const MCP_ALL_TRANSPORTS: readonly McpTransport[] = [
  "stdio",
  "sse",
  "streamableHttp",
];

/**
 * The transports a person may configure for themselves. stdio is absent by
 * design and permanently: its `command` runs on the host as the application
 * user, which is why it stays in the admin registry.
 */
export const MCP_REMOTE_TRANSPORTS: readonly McpTransport[] = [
  "sse",
  "streamableHttp",
];

// Mirrors `_SERVER_NAME_RE` in deeptutor/services/mcp/config.py: an invalid name
// is rejected there with a 400, so the form checks it first and reports inline.
export const MCP_SERVER_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

export function isValidMcpServerName(name: string): boolean {
  return MCP_SERVER_NAME_RE.test(name);
}

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
    disabled_tools: [],
    enabled: true,
    auth: "",
    catalog_entry: "",
  };
}

// ── helpers: array <-> textarea (one item per line) ───────────────────────

export function linesToArray(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function arrayToLines(value: string[]): string {
  return value.join("\n");
}

// ── helpers: dict <-> editable key/value rows ────────────────────────────

export type McpKvPair = { key: string; value: string };

export function dictToPairs(dict: Record<string, string>): McpKvPair[] {
  return Object.entries(dict).map(([key, value]) => ({ key, value }));
}

export function pairsToDict(pairs: McpKvPair[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of pairs) {
    const k = key.trim();
    if (k) out[k] = value;
  }
  return out;
}

// ── helpers: transport ───────────────────────────────────────────────────

/**
 * Resolve the effective transport the same way the backend does
 * (`MCPServerConfig.resolved_type`), so the UI can preview the auto-detected
 * type before saving.
 */
export function resolveMcpTransport(cfg: McpServerConfig): McpTransport | null {
  if (cfg.type) return cfg.type;
  if (cfg.command.trim()) return "stdio";
  if (cfg.url.trim()) {
    return cfg.url.replace(/\/+$/, "").endsWith("/sse")
      ? "sse"
      : "streamableHttp";
  }
  return null;
}

export function isRemoteMcpTransport(transport: McpTransport | null): boolean {
  return transport === "sse" || transport === "streamableHttp";
}

/**
 * The status to render for one server row.
 *
 * `cfg.enabled` wins over the live status row: disabling a server makes the
 * manager drop the connection *before* it is marked disabled
 * (`_sync_to_config` pops the entry, then `_disconnect` sets the status), so a
 * disabled server has no row at all — and a missing row otherwise means
 * "connecting". Reading the row first therefore left disabled servers stuck on
 * "Connecting" forever.
 */
export function mcpRowStatus(
  cfg: McpServerConfig,
  row: McpStatusRow | undefined,
): McpServerStatus {
  if (!cfg.enabled) return "disabled";
  return row?.status ?? "connecting";
}

// ── helpers: form draft -> config ────────────────────────────────────────

/** The fields the add/edit form owns, in their raw editor shape. */
export interface McpServerFormDraft {
  type: McpTransport | null;
  command: string;
  argsText: string;
  envPairs: McpKvPair[];
  cwd: string;
  url: string;
  headerPairs: McpKvPair[];
  toolTimeout: number;
  enabledToolsText: string;
}

/**
 * Build the config to persist from a form draft.
 *
 * `base` is the entry being edited (or `emptyMcpServerConfig()` for a new one).
 * Fields the form does not expose — `enabled`, `disabled_tools`,
 * `catalog_entry` — are carried over from it rather than defaulted away, so a UI
 * save never clobbers state it cannot show.
 */
export function buildMcpServerConfig(
  draft: McpServerFormDraft,
  base: McpServerConfig,
): McpServerConfig {
  const enabledTools = linesToArray(draft.enabledToolsText);
  return {
    type: draft.type,
    command: draft.command.trim(),
    args: linesToArray(draft.argsText),
    env: pairsToDict(draft.envPairs),
    cwd: draft.cwd.trim(),
    url: draft.url.trim(),
    headers: pairsToDict(draft.headerPairs),
    tool_timeout: draft.toolTimeout,
    enabled_tools: enabledTools.length > 0 ? enabledTools : ["*"],
    disabled_tools: [...base.disabled_tools],
    enabled: base.enabled,
    auth: base.auth,
    catalog_entry: base.catalog_entry,
  };
}

// ── transport ────────────────────────────────────────────────────────────

/**
 * A refused MCP request, carrying the backend's machine-readable reason.
 *
 * The per-user routes answer a refusal with `detail: {code, message}` precisely
 * so the client can render its own copy — the raw messages are English strings
 * built server-side and several of them need an actionable next step, not a
 * translation.
 */
export class McpApiError extends Error {
  /** Backend refusal code (`detail.code`), or `""` when it sent none. */
  readonly code: string;

  constructor(message: string, code = "") {
    super(message);
    this.name = "McpApiError";
    this.code = code;
  }
}

async function asJson(response: Response) {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let code = "";
    try {
      const body = await response.json();
      const detail = (body as { detail?: unknown } | null)?.detail;
      if (detail && typeof detail === "object") {
        const shaped = detail as { code?: unknown; message?: unknown };
        code = String(shaped.code ?? "");
        // Stringifying the object itself is how a refusal used to reach the UI
        // as "[object Object]".
        if (shaped.message) message = String(shaped.message);
      } else if (detail) {
        message = String(detail);
      }
    } catch {
      /* ignore */
    }
    throw new McpApiError(message, code);
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
    "needs_auth",
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

export function normalizeServerConfig(raw: unknown): McpServerConfig {
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
    disabled_tools: Array.isArray(item.disabled_tools)
      ? item.disabled_tools.map((a) => String(a))
      : base.disabled_tools,
    enabled: item.enabled === undefined ? base.enabled : Boolean(item.enabled),
    auth: item.auth === "oauth" ? "oauth" : base.auth,
    catalog_entry: String(item.catalog_entry ?? base.catalog_entry),
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

function normalizeStatusRows(raw: unknown): McpStatusRow[] {
  return Array.isArray(raw) ? raw.map(normalizeStatusRow) : [];
}

function normalizeTestResult(raw: unknown): McpTestResult {
  const data = (raw ?? {}) as Record<string, unknown>;
  return {
    ok: Boolean(data.ok),
    tools: Array.isArray(data.tools) ? data.tools.map(normalizeTool) : [],
    error: String(data.error ?? ""),
  };
}

function normalizeOauthMap(
  raw: unknown,
): Record<string, { required: boolean; authorized: boolean }> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, { required: boolean; authorized: boolean }> = {};
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    const row = (value ?? {}) as { required?: unknown; authorized?: unknown };
    out[name] = {
      required: row.required === undefined ? true : Boolean(row.required),
      authorized: Boolean(row.authorized),
    };
  }
  return out;
}

function normalizeStringList(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.map((item) => String(item)) : [];
}

function normalizeStoreState(raw: unknown): McpStoreState {
  const data = (raw ?? {}) as Record<string, unknown>;
  const deployment = (data.deployment ?? {}) as Record<string, unknown>;
  const limits = (data.limits ?? {}) as Record<string, unknown>;
  const secrets = (data.configured_secrets ?? {}) as Record<string, unknown>;
  return {
    servers: normalizeServers(data.servers),
    status: normalizeStatusRows(data.status),
    user: {
      configuredSecrets: Object.fromEntries(
        Object.entries(secrets).map(([name, fields]) => [
          name,
          normalizeStringList(fields),
        ]),
      ),
      rejected: Array.isArray(data.rejected)
        ? data.rejected.map((row) => {
            const item = (row ?? {}) as { name?: unknown; reason?: unknown };
            return {
              name: String(item.name ?? ""),
              reason: String(item.reason ?? ""),
            };
          })
        : [],
      deployment: {
        servers: normalizeStringList(deployment.servers),
        status: normalizeStatusRows(deployment.status),
      },
      oauth: normalizeOauthMap(data.oauth),
      // Left at 0 rather than mirroring the backend's constant: a cap the UI
      // invented would report a limit nothing enforces.
      maxServers:
        typeof limits.max_servers === "number" &&
        Number.isFinite(limits.max_servers)
          ? limits.max_servers
          : 0,
    },
  };
}

// `basePath` is explicit — the same components drive both the admin registry
// and the per-user one, and defaulting it would let a per-user page silently
// read or write the deployment-global config.
export async function getMcpSettings(basePath: string): Promise<McpSettings> {
  const response = await apiFetch(apiUrl(basePath), {
    cache: "no-store",
  });
  const data = await asJson(response);
  return {
    servers: normalizeServers(data?.servers),
    status: normalizeStatusRows(data?.status),
  };
}

export async function updateMcpSettings(
  basePath: string,
  servers: Record<string, McpServerConfig>,
): Promise<McpStatusRow[]> {
  const response = await apiFetch(apiUrl(basePath), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ servers }),
  });
  const data = await asJson(response);
  return normalizeStatusRows(data?.status);
}

export async function testMcpServer(
  basePath: string,
  cfg: McpServerConfig,
): Promise<McpTestResult> {
  const response = await apiFetch(apiUrl(`${basePath}/test`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  return normalizeTestResult(await asJson(response));
}

// ── per-user store ───────────────────────────────────────────────────────
//
// The per-user surface writes one server at a time (`PUT /servers/{name}`)
// instead of PUTting the whole map: a save must not be able to drop a server it
// never showed, and the response carries the fresh state so the caller never
// has to guess what the file now holds.

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function getSpaceMcpState(
  basePath: string,
): Promise<McpStoreState> {
  const response = await apiFetch(apiUrl(`${basePath}/servers`), {
    cache: "no-store",
  });
  return normalizeStoreState(await asJson(response));
}

/**
 * Upsert one of the caller's servers.
 *
 * `secrets` is field name → value: the backend stores each apart from the
 * config and replaces any literal copy inside `cfg` with a reference, so a
 * value pasted into a header never lands on disk. An empty string clears a
 * stored field.
 */
export async function putSpaceMcpServer(
  basePath: string,
  name: string,
  cfg: McpServerConfig,
  secrets: Record<string, string> = {},
): Promise<McpStoreState> {
  const response = await apiFetch(
    apiUrl(`${basePath}/servers/${encodeURIComponent(name)}`),
    {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ config: cfg, secrets }),
    },
  );
  return normalizeStoreState(await asJson(response));
}

export async function deleteSpaceMcpServer(
  basePath: string,
  name: string,
): Promise<McpStoreState> {
  const response = await apiFetch(
    apiUrl(`${basePath}/servers/${encodeURIComponent(name)}`),
    { method: "DELETE" },
  );
  return normalizeStoreState(await asJson(response));
}

/**
 * Begin an OAuth consent for one of the caller's servers.
 *
 * Answers with the URL to send the person to; the browser comes back to the
 * app's own callback route, which completes the exchange server-side.
 */
export async function authorizeSpaceMcpServer(
  basePath: string,
  name: string,
): Promise<string> {
  const response = await apiFetch(
    apiUrl(`${basePath}/servers/${encodeURIComponent(name)}/authorize`),
    { method: "POST", headers: JSON_HEADERS },
  );
  const data = await asJson(response);
  return String(data?.authorize_url ?? "");
}

export async function testSpaceMcpServer(
  basePath: string,
  name: string,
  cfg: McpServerConfig,
  secrets: Record<string, string> = {},
): Promise<McpTestResult> {
  const response = await apiFetch(
    apiUrl(`${basePath}/servers/${encodeURIComponent(name)}/test`),
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ config: cfg, secrets }),
    },
  );
  return normalizeTestResult(await asJson(response));
}

// ── catalog ──────────────────────────────────────────────────────────────

/** One credential an entry asks the installer for. */
export interface McpCatalogField {
  key: string;
  label_i18n: Record<string, string>;
  /** Render as a password input and store apart from the config. */
  secret: boolean;
  required: boolean;
  placeholder: string;
}

export interface McpCatalogEntry {
  id: string;
  display_name: string;
  description_i18n: Record<string, string>;
  category: string;
  tier: string;
  transport: string;
  homepage: string;
  docs_url: string;
  requires_i18n: Record<string, string>;
  /**
   * Relative path the app serves itself, or `""` for an initials avatar. Never
   * a third-party URL: one logo fetch per installed service would hand that
   * vendor the viewer's app list on every render.
   */
  logo_url: string;
  trust: string;
  self_service: boolean;
  installed: boolean;
  /**
   * Local names this entry is installed under, by recorded provenance. The
   * installer picks the name, so this — not the entry id — is what identifies
   * the server to test or reinstall.
   */
  installed_as: string[];
  fields: McpCatalogField[];
}

export interface McpCatalogPage {
  entries: McpCatalogEntry[];
  /** Empty once the last page has been served. */
  next_cursor: string;
  /** Matches before pagination. */
  total: number;
  /** Category → match count, for a filter row that hides its empty chips. */
  categories: Record<string, number>;
}

export interface McpCatalogQuery {
  q?: string;
  category?: string;
  tier?: string;
  cursor?: string;
  limit?: number;
}

function normalizeI18nMap(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, string> = {};
  for (const [lang, text] of Object.entries(raw as Record<string, unknown>)) {
    out[lang] = String(text ?? "");
  }
  return out;
}

function normalizeCatalogField(raw: unknown): McpCatalogField {
  const item = (raw ?? {}) as Record<string, unknown>;
  return {
    key: String(item.key ?? ""),
    label_i18n: normalizeI18nMap(item.label_i18n),
    secret: item.secret === undefined ? true : Boolean(item.secret),
    required: item.required === undefined ? true : Boolean(item.required),
    placeholder: String(item.placeholder ?? ""),
  };
}

function normalizeCatalogEntry(raw: unknown): McpCatalogEntry {
  const item = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(item.id ?? ""),
    display_name: String(item.display_name ?? ""),
    description_i18n: normalizeI18nMap(item.description_i18n),
    category: String(item.category ?? ""),
    tier: String(item.tier ?? ""),
    transport: String(item.transport ?? ""),
    homepage: String(item.homepage ?? ""),
    docs_url: String(item.docs_url ?? ""),
    requires_i18n: normalizeI18nMap(item.requires_i18n),
    logo_url: String(item.logo_url ?? ""),
    trust: String(item.trust ?? ""),
    self_service:
      item.self_service === undefined ? true : Boolean(item.self_service),
    installed: Boolean(item.installed),
    installed_as: normalizeStringList(item.installed_as),
    fields: Array.isArray(item.fields)
      ? item.fields.map(normalizeCatalogField)
      : [],
  };
}

export async function getMcpCatalog(
  basePath: string,
  query: McpCatalogQuery = {},
): Promise<McpCatalogPage> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.category) params.set("category", query.category);
  if (query.tier) params.set("tier", query.tier);
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.limit) params.set("limit", String(query.limit));
  const search = params.toString();
  const response = await apiFetch(
    apiUrl(`${basePath}/catalog${search ? `?${search}` : ""}`),
    { cache: "no-store" },
  );
  const data = await asJson(response);
  const counts = (data?.categories ?? {}) as Record<string, unknown>;
  return {
    entries: Array.isArray(data?.entries)
      ? data.entries.map(normalizeCatalogEntry)
      : [],
    next_cursor: String(data?.next_cursor ?? ""),
    total: typeof data?.total === "number" ? data.total : 0,
    categories: Object.fromEntries(
      Object.entries(counts).map(([category, count]) => [
        category,
        typeof count === "number" ? count : 0,
      ]),
    ),
  };
}

/** Install a catalog entry for the caller. `name` defaults to the entry id. */
export async function installMcpCatalogEntry(
  basePath: string,
  entryId: string,
  opts: { name?: string; secrets?: Record<string, string> } = {},
): Promise<McpStoreState> {
  const response = await apiFetch(
    apiUrl(`${basePath}/catalog/${encodeURIComponent(entryId)}/install`),
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        name: opts.name ?? "",
        secrets: opts.secrets ?? {},
      }),
    },
  );
  return normalizeStoreState(await asJson(response));
}
