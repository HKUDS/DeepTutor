"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Pencil, Plug, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsPageHeader } from "@/components/settings/shared";
import {
  emptyMcpServerConfig,
  getMcpSettings,
  testMcpServer,
  updateMcpSettings,
  type McpServerConfig,
  type McpServerStatus,
  type McpStatusRow,
  type McpTool,
  type McpTransport,
} from "@/lib/mcp-api";

const inputClass =
  "w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/40 focus:border-[var(--ring)]";
const selectClass =
  "w-full appearance-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]";
const labelClass =
  "mb-1.5 block text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80";

const SERVER_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

// ── helpers: array <-> textarea (one item per line) ───────────────────────
function linesToArray(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function arrayToLines(value: string[]): string {
  return value.join("\n");
}

type KvPair = { key: string; value: string };

function dictToPairs(dict: Record<string, string>): KvPair[] {
  return Object.entries(dict).map(([key, value]) => ({ key, value }));
}

function pairsToDict(pairs: KvPair[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of pairs) {
    const k = key.trim();
    if (k) out[k] = value;
  }
  return out;
}

// Resolve the effective transport the same way the backend does, so the UI
// can preview the auto-detected type before saving.
function resolveTransport(cfg: McpServerConfig): McpTransport | null {
  if (cfg.type) return cfg.type;
  if (cfg.command.trim()) return "stdio";
  if (cfg.url.trim()) {
    return cfg.url.replace(/\/+$/, "").endsWith("/sse")
      ? "sse"
      : "streamableHttp";
  }
  return null;
}

function isRemoteTransport(transport: McpTransport | null): boolean {
  return transport === "sse" || transport === "streamableHttp";
}

export default function McpSettingsPage() {
  const { t } = useTranslation();

  const [servers, setServers] = useState<Record<
    string,
    McpServerConfig
  > | null>(null);
  const [statusRows, setStatusRows] = useState<McpStatusRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Editing key: a server name for edit, "" for the "add new" form, or null
  // when no editor is open.
  const [editingKey, setEditingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getMcpSettings();
      setServers(data.servers);
      setStatusRows(data.status);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const statusByName = useMemo(() => {
    const map = new Map<string, McpStatusRow>();
    for (const row of statusRows) map.set(row.name, row);
    return map;
  }, [statusRows]);

  const persist = useCallback(async (next: Record<string, McpServerConfig>) => {
    setSaving(true);
    setSaveError(null);
    try {
      const status = await updateMcpSettings(next);
      setServers(next);
      setStatusRows(status);
      return true;
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, []);

  const handleToggleExpanded = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleToggleEnabled = useCallback(
    async (name: string) => {
      if (!servers || saving) return;
      const current = servers[name];
      if (!current) return;
      const next = {
        ...servers,
        [name]: { ...current, enabled: !current.enabled },
      };
      await persist(next);
    },
    [servers, saving, persist],
  );

  const handleDelete = useCallback(
    async (name: string) => {
      if (!servers || saving) return;
      if (
        typeof window !== "undefined" &&
        !window.confirm(t('Delete MCP server "{{name}}"?', { name }))
      ) {
        return;
      }
      const next = { ...servers };
      delete next[name];
      if (editingKey === name) setEditingKey(null);
      await persist(next);
    },
    [servers, saving, t, editingKey, persist],
  );

  const handleSaveEditor = useCallback(
    async (originalName: string | "", name: string, cfg: McpServerConfig) => {
      if (!servers) return false;
      const next = { ...servers };
      // Rename: drop the old key when editing under a new name.
      if (originalName && originalName !== name) delete next[originalName];
      next[name] = cfg;
      const ok = await persist(next);
      if (ok) setEditingKey(null);
      return ok;
    },
    [servers, persist],
  );

  const serverNames = useMemo(
    () => (servers ? Object.keys(servers).sort() : []),
    [servers],
  );

  return (
    <div data-tour="tour-mcp">
      <SettingsPageHeader
        title={t("MCP servers")}
        description={t(
          "Connect external MCP (Model Context Protocol) servers to extend the agent's capabilities.",
        )}
      />

      {loadError && (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/5 px-4 py-3 text-[12px] text-red-500">
          {t("Failed to load MCP servers")}: {loadError}
        </div>
      )}

      {saveError && (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/5 px-4 py-3 text-[12px] text-red-500">
          {t("Failed to save")}: {saveError}
        </div>
      )}

      {!servers && !loadError && (
        <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("Loading...")}
        </div>
      )}

      {servers && (
        <div className="space-y-6">
          {serverNames.length === 0 && editingKey === null && (
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)]/70 bg-[var(--card)]/30 px-6 py-14 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--muted)]/60">
                <Plug className="h-4 w-4 text-[var(--muted-foreground)]" />
              </div>
              <div className="text-[14px] font-medium text-[var(--foreground)]">
                {t("No MCP servers yet")}
              </div>
              <p className="max-w-md text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Add a server to expose its tools to the chat agent. Test the connection first, then save.",
                )}
              </p>
            </div>
          )}

          {serverNames.length > 0 && (
            <div className="overflow-hidden rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40">
              {serverNames.map((name, idx) => {
                const cfg = servers[name];
                const status = statusByName.get(name);
                const isExpanded = expanded.has(name);
                const isEditing = editingKey === name;
                return (
                  <div
                    key={name}
                    className={
                      idx > 0 ? "border-t border-[var(--border)]/50" : undefined
                    }
                  >
                    <ServerRow
                      name={name}
                      cfg={cfg}
                      status={status}
                      isExpanded={isExpanded}
                      saving={saving}
                      onToggleExpanded={() => handleToggleExpanded(name)}
                      onToggleEnabled={() => handleToggleEnabled(name)}
                      onEdit={() =>
                        setEditingKey((prev) => (prev === name ? null : name))
                      }
                      onDelete={() => handleDelete(name)}
                    />
                    {isExpanded && status && status.tools.length > 0 && (
                      <ToolList tools={status.tools} />
                    )}
                    {isEditing && (
                      <div className="border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-5 py-5">
                        <ServerForm
                          originalName={name}
                          initialName={name}
                          initialConfig={cfg}
                          existingNames={serverNames}
                          saving={saving}
                          onCancel={() => setEditingKey(null)}
                          onSave={handleSaveEditor}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {editingKey === "" ? (
            <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 px-5 py-5">
              <div className="mb-4 text-[13px] font-semibold text-[var(--foreground)]">
                {t("Add MCP server")}
              </div>
              <ServerForm
                originalName=""
                initialName=""
                initialConfig={emptyMcpServerConfig()}
                existingNames={serverNames}
                saving={saving}
                onCancel={() => setEditingKey(null)}
                onSave={handleSaveEditor}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setEditingKey("")}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("Add server")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── status badge ──────────────────────────────────────────────────────────
function StatusBadge({
  status,
  error,
}: {
  status: McpServerStatus | undefined;
  error?: string;
}) {
  const { t } = useTranslation();
  const labels: Record<McpServerStatus, string> = {
    connected: t("Connected"),
    connecting: t("Connecting"),
    error: t("Error"),
    disabled: t("Disabled"),
  };
  const dotClass: Record<McpServerStatus, string> = {
    connected: "bg-emerald-500",
    connecting: "bg-amber-400",
    error: "bg-red-500",
    disabled: "bg-[var(--border)]",
  };
  const effective: McpServerStatus = status ?? "connecting";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--muted)]/30 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]"
      title={effective === "error" && error ? error : undefined}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${dotClass[effective]}`}
        aria-hidden
      />
      {labels[effective]}
    </span>
  );
}

// ── one server row ──────────────────────────────────────────────────────
function ServerRow({
  name,
  cfg,
  status,
  isExpanded,
  saving,
  onToggleExpanded,
  onToggleEnabled,
  onEdit,
  onDelete,
}: {
  name: string;
  cfg: McpServerConfig;
  status: McpStatusRow | undefined;
  isExpanded: boolean;
  saving: boolean;
  onToggleExpanded: () => void;
  onToggleEnabled: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const transport = status?.transport || resolveTransport(cfg) || "";
  const toolCount = status?.tools.length ?? 0;
  return (
    <div className="flex w-full items-start gap-3 px-5 py-4">
      <Plug className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex min-w-0 flex-1 items-start gap-3 text-left"
        aria-expanded={isExpanded}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[13px] font-medium text-[var(--foreground)]">
              {name}
            </span>
            {transport && (
              <span className="rounded-full bg-[var(--muted)]/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {transport}
              </span>
            )}
            <StatusBadge status={status?.status} error={status?.error} />
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {cfg.command || cfg.url || t("Not configured")}
            {" · "}
            {t("{{count}} tools", { count: toolCount })}
          </p>
          {status?.status === "error" && status.error && (
            <p className="mt-1 text-[11.5px] leading-relaxed text-red-500">
              {status.error}
            </p>
          )}
        </div>
        <ChevronDown
          className={`mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform ${
            isExpanded ? "rotate-180" : ""
          }`}
        />
      </button>
      <div className="mt-0.5 flex shrink-0 items-center gap-1.5">
        <Toggle
          checked={cfg.enabled}
          disabled={saving}
          onChange={onToggleEnabled}
          label={cfg.enabled ? t("Enabled") : t("Disabled")}
        />
        <IconButton
          label={t("Edit")}
          onClick={onEdit}
          disabled={saving}
          icon={<Pencil className="h-3.5 w-3.5" />}
        />
        <IconButton
          label={t("Delete")}
          onClick={onDelete}
          disabled={saving}
          icon={<Trash2 className="h-3.5 w-3.5" />}
          danger
        />
      </div>
    </div>
  );
}

function ToolList({ tools }: { tools: McpTool[] }) {
  const { t } = useTranslation();
  return (
    <div className="border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-5 py-4">
      <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
        {t("Exposed tools")}
      </div>
      <ul className="space-y-1.5">
        {tools.map((tool) => (
          <li key={tool.name} className="flex items-baseline gap-2">
            <span className="font-mono text-[12px] text-[var(--foreground)]">
              {tool.name}
            </span>
            {tool.description && (
              <span className="text-[12px] text-[var(--muted-foreground)]">
                — {tool.description}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── add / edit form ─────────────────────────────────────────────────────
function ServerForm({
  originalName,
  initialName,
  initialConfig,
  existingNames,
  saving,
  onCancel,
  onSave,
}: {
  originalName: string | "";
  initialName: string;
  initialConfig: McpServerConfig;
  existingNames: string[];
  saving: boolean;
  onCancel: () => void;
  onSave: (
    originalName: string | "",
    name: string,
    cfg: McpServerConfig,
  ) => Promise<boolean>;
}) {
  const { t } = useTranslation();

  const [name, setName] = useState(initialName);
  const [type, setType] = useState<McpServerConfig["type"]>(initialConfig.type);
  const [command, setCommand] = useState(initialConfig.command);
  const [argsText, setArgsText] = useState(arrayToLines(initialConfig.args));
  const [envPairs, setEnvPairs] = useState<KvPair[]>(
    dictToPairs(initialConfig.env),
  );
  const [cwd, setCwd] = useState(initialConfig.cwd);
  const [url, setUrl] = useState(initialConfig.url);
  const [headerPairs, setHeaderPairs] = useState<KvPair[]>(
    dictToPairs(initialConfig.headers),
  );
  const [toolTimeout, setToolTimeout] = useState(initialConfig.tool_timeout);
  const [enabledToolsText, setEnabledToolsText] = useState(
    arrayToLines(initialConfig.enabled_tools),
  );

  const [testing, setTesting] = useState(false);
  const [testTools, setTestTools] = useState<McpTool[] | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const buildConfig = useCallback((): McpServerConfig => {
    const enabledTools = linesToArray(enabledToolsText);
    return {
      type,
      command: command.trim(),
      args: linesToArray(argsText),
      env: pairsToDict(envPairs),
      cwd: cwd.trim(),
      url: url.trim(),
      headers: pairsToDict(headerPairs),
      tool_timeout: toolTimeout,
      enabled_tools: enabledTools.length > 0 ? enabledTools : ["*"],
      enabled: initialConfig.enabled,
    };
  }, [
    type,
    command,
    argsText,
    envPairs,
    cwd,
    url,
    headerPairs,
    toolTimeout,
    enabledToolsText,
    initialConfig.enabled,
  ]);

  const effectiveTransport = resolveTransport(buildConfig());
  const showStdio = effectiveTransport === "stdio" || type === "stdio";
  const showRemote =
    isRemoteTransport(effectiveTransport) ||
    type === "sse" ||
    type === "streamableHttp";

  const validateName = useCallback((): string | null => {
    const trimmed = name.trim();
    if (!trimmed) return t("Server name is required.");
    if (!SERVER_NAME_RE.test(trimmed)) {
      return t(
        "Server name must start alphanumeric and use only letters, digits, - or _ (max 64).",
      );
    }
    if (trimmed !== originalName && existingNames.includes(trimmed)) {
      return t("A server with this name already exists.");
    }
    return null;
  }, [name, originalName, existingNames, t]);

  const handleTest = useCallback(async () => {
    setFormError(null);
    setTestError(null);
    setTestTools(null);
    const cfg = buildConfig();
    if (resolveTransport(cfg) === null) {
      setTestError(
        t("Configure either a command (stdio) or a url before testing."),
      );
      return;
    }
    setTesting(true);
    try {
      const result = await testMcpServer(cfg);
      if (result.ok) {
        setTestTools(result.tools);
      } else {
        setTestError(result.error || t("Connection failed."));
      }
    } catch (err) {
      setTestError(err instanceof Error ? err.message : String(err));
    } finally {
      setTesting(false);
    }
  }, [buildConfig, t]);

  const handleSave = useCallback(async () => {
    const nameError = validateName();
    if (nameError) {
      setFormError(nameError);
      return;
    }
    const cfg = buildConfig();
    if (resolveTransport(cfg) === null) {
      setFormError(
        t("Configure either a command (stdio) or a url before saving."),
      );
      return;
    }
    setFormError(null);
    await onSave(originalName, name.trim(), cfg);
  }, [validateName, buildConfig, onSave, originalName, name, t]);

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass}>{t("Name")}</label>
          <input
            className={inputClass}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-server"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div>
          <label className={labelClass}>{t("Transport")}</label>
          <select
            className={selectClass}
            value={type ?? ""}
            onChange={(e) =>
              setType((e.target.value || null) as McpServerConfig["type"])
            }
          >
            <option value="">
              {t("Auto-detect")}
              {effectiveTransport ? ` (${effectiveTransport})` : ""}
            </option>
            <option value="stdio">stdio</option>
            <option value="sse">sse</option>
            <option value="streamableHttp">streamableHttp</option>
          </select>
        </div>
      </div>

      {showStdio && (
        <div className="space-y-4 rounded-lg border border-[var(--border)]/50 bg-[var(--card)]/30 px-4 py-4">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
            {t("Standard I/O (local process)")}
          </div>
          <div>
            <label className={labelClass}>{t("Command")}</label>
            <input
              className={`${inputClass} font-mono`}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="npx"
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelClass}>
              {t("Arguments (one per line)")}
            </label>
            <textarea
              className={`${inputClass} min-h-[72px] resize-y font-mono`}
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              placeholder={"-y\n@modelcontextprotocol/server-filesystem"}
              spellCheck={false}
            />
          </div>
          <div>
            <label className={labelClass}>
              {t("Working directory (optional)")}
            </label>
            <input
              className={`${inputClass} font-mono`}
              value={cwd}
              onChange={(e) => setCwd(e.target.value)}
              placeholder="/path/to/workdir"
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <KeyValueEditor
            label={t("Environment variables")}
            pairs={envPairs}
            onChange={setEnvPairs}
            keyPlaceholder="KEY"
            valuePlaceholder="value"
          />
        </div>
      )}

      {showRemote && (
        <div className="space-y-4 rounded-lg border border-[var(--border)]/50 bg-[var(--card)]/30 px-4 py-4">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
            {t("Remote (SSE / streamable HTTP)")}
          </div>
          <div>
            <label className={labelClass}>{t("Server URL")}</label>
            <input
              className={`${inputClass} font-mono`}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/mcp"
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <KeyValueEditor
            label={t("HTTP headers")}
            pairs={headerPairs}
            onChange={setHeaderPairs}
            keyPlaceholder="Authorization"
            valuePlaceholder="Bearer ..."
          />
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass}>{t("Tool timeout (seconds)")}</label>
          <input
            type="number"
            min={1}
            max={600}
            className={inputClass}
            value={toolTimeout}
            onChange={(e) => {
              const n = Number(e.target.value);
              setToolTimeout(
                Number.isFinite(n) ? Math.min(600, Math.max(1, n)) : 30,
              );
            }}
          />
        </div>
        <div>
          <label className={labelClass}>
            {t("Enabled tools (one per line, * = all)")}
          </label>
          <textarea
            className={`${inputClass} min-h-[60px] resize-y font-mono`}
            value={enabledToolsText}
            onChange={(e) => setEnabledToolsText(e.target.value)}
            placeholder="*"
            spellCheck={false}
          />
        </div>
      </div>

      {/* Test result */}
      {testError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
          {t("Connection failed.")} {testError}
        </div>
      )}
      {testTools && (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 px-3 py-3">
          <div className="mb-2 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
            {t("Connected — {{count}} tools detected", {
              count: testTools.length,
            })}
          </div>
          {testTools.length > 0 && (
            <ul className="space-y-1">
              {testTools.map((tool) => (
                <li key={tool.name} className="flex items-baseline gap-2">
                  <span className="font-mono text-[12px] text-[var(--foreground)]">
                    {tool.name}
                  </span>
                  {tool.description && (
                    <span className="text-[11.5px] text-[var(--muted-foreground)]">
                      — {tool.description}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {formError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
          {formError}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          onClick={handleTest}
          disabled={testing || saving}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {testing && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("Test connection")}
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || testing}
          className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("Save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded-lg px-3.5 py-2 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("Cancel")}
        </button>
      </div>
    </div>
  );
}

// ── key/value editor (env, headers) ─────────────────────────────────────
function KeyValueEditor({
  label,
  pairs,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
}: {
  label: string;
  pairs: KvPair[];
  onChange: (pairs: KvPair[]) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}) {
  const { t } = useTranslation();
  const update = (idx: number, patch: Partial<KvPair>) => {
    onChange(pairs.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };
  const remove = (idx: number) => {
    onChange(pairs.filter((_, i) => i !== idx));
  };
  const add = () => {
    onChange([...pairs, { key: "", value: "" }]);
  };
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <div className="space-y-2">
        {pairs.map((pair, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              className={`${inputClass} font-mono`}
              value={pair.key}
              onChange={(e) => update(idx, { key: e.target.value })}
              placeholder={keyPlaceholder}
              spellCheck={false}
              autoComplete="off"
            />
            <input
              className={`${inputClass} font-mono`}
              value={pair.value}
              onChange={(e) => update(idx, { value: e.target.value })}
              placeholder={valuePlaceholder}
              spellCheck={false}
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => remove(idx)}
              aria-label={t("Remove")}
              className="shrink-0 rounded-md p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-500"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <Plus className="h-3 w-3" />
          {t("Add row")}
        </button>
      </div>
    </div>
  );
}

// ── small controls ──────────────────────────────────────────────────────
function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onChange}
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full border transition-colors ${
        checked
          ? "border-[var(--primary)] bg-[var(--primary)]/70"
          : "border-[var(--border)] bg-[var(--muted)]/50"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
    >
      <span
        className={`inline-block h-[12px] w-[12px] transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-[16px]" : "translate-x-[2px]"
        }`}
      />
    </button>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  icon,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  icon: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] ${
        danger ? "hover:text-red-500" : "hover:text-[var(--foreground)]"
      } disabled:cursor-not-allowed disabled:opacity-60`}
    >
      {icon}
    </button>
  );
}
