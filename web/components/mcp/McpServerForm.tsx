"use client";

import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import KeyValueEditor from "@/components/mcp/KeyValueEditor";
import { inputClass, labelClass, selectClass } from "@/components/mcp/styles";
import {
  surfaceAllows,
  testMcpSurfaceServer,
  type McpSurface,
} from "@/components/mcp/surface";
import {
  arrayToLines,
  buildMcpServerConfig,
  dictToPairs,
  isRemoteMcpTransport,
  isValidMcpServerName,
  resolveMcpTransport,
  type McpKvPair,
  type McpServerConfig,
  type McpTool,
} from "@/lib/mcp-api";
import { describeMcpError } from "@/lib/mcp-store";

export default function McpServerForm({
  surface,
  originalName,
  initialName,
  initialConfig,
  existingNames,
  saving,
  onCancel,
  onSave,
}: {
  surface: McpSurface;
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
  const [envPairs, setEnvPairs] = useState<McpKvPair[]>(
    dictToPairs(initialConfig.env),
  );
  const [cwd, setCwd] = useState(initialConfig.cwd);
  const [url, setUrl] = useState(initialConfig.url);
  const [headerPairs, setHeaderPairs] = useState<McpKvPair[]>(
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

  const buildConfig = useCallback(
    (): McpServerConfig =>
      buildMcpServerConfig(
        {
          type,
          command,
          argsText,
          envPairs,
          cwd,
          url,
          headerPairs,
          toolTimeout,
          enabledToolsText,
        },
        initialConfig,
      ),
    [
      type,
      command,
      argsText,
      envPairs,
      cwd,
      url,
      headerPairs,
      toolTimeout,
      enabledToolsText,
      initialConfig,
    ],
  );

  const stdioAllowed = surfaceAllows(surface, "stdio");
  const effectiveTransport = resolveMcpTransport(buildConfig());
  const showStdio =
    stdioAllowed && (effectiveTransport === "stdio" || type === "stdio");
  // A surface without stdio has only one kind of server to describe, so the
  // remote block is shown from the start: an empty form whose URL field appears
  // only after picking a transport is a dead end.
  const showRemote =
    !stdioAllowed ||
    isRemoteMcpTransport(effectiveTransport) ||
    type === "sse" ||
    type === "streamableHttp";

  const validateName = useCallback((): string | null => {
    const trimmed = name.trim();
    if (!trimmed) return t("Server name is required.");
    if (!isValidMcpServerName(trimmed)) {
      return t(
        "Server name must start alphanumeric and use only letters, digits, - or _ (max 64).",
      );
    }
    if (trimmed !== originalName && existingNames.includes(trimmed)) {
      return t("A server with this name already exists.");
    }
    return null;
  }, [name, originalName, existingNames, t]);

  // Copy has to follow the surface: on a per-user surface stdio is not offered,
  // so telling someone to "configure a command" points at a control that is
  // deliberately absent.
  const missingTargetMessage = stdioAllowed
    ? t("Configure either a command (stdio) or a url first.")
    : t("Enter the server's https URL first.");

  const handleTest = useCallback(async () => {
    setFormError(null);
    setTestError(null);
    setTestTools(null);
    const cfg = buildConfig();
    if (resolveMcpTransport(cfg) === null) {
      setTestError(missingTargetMessage);
      return;
    }
    setTesting(true);
    try {
      const result = await testMcpSurfaceServer(surface, name, cfg);
      if (result.ok) {
        setTestTools(result.tools);
      } else {
        setTestError(result.error || t("Connection failed."));
      }
    } catch (err) {
      setTestError(describeMcpError(err, t));
    } finally {
      setTesting(false);
    }
  }, [buildConfig, missingTargetMessage, surface, name, t]);

  const handleSave = useCallback(async () => {
    const nameError = validateName();
    if (nameError) {
      setFormError(nameError);
      return;
    }
    const cfg = buildConfig();
    if (resolveMcpTransport(cfg) === null) {
      setFormError(missingTargetMessage);
      return;
    }
    setFormError(null);
    await onSave(originalName, name.trim(), cfg);
  }, [
    validateName,
    buildConfig,
    missingTargetMessage,
    onSave,
    originalName,
    name,
  ]);

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
            {surface.transports.map((transport) => (
              <option key={transport} value={transport}>
                {transport}
              </option>
            ))}
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
