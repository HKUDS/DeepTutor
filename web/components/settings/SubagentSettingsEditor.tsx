"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  selectClass,
  inputClass,
} from "@/components/settings/shared";
import { Toggle } from "@/components/settings/Toggle";
import { agentGlyph } from "@/components/agents/agent-icons";
import {
  getBackendOptions,
  getSubagentSettings,
  syncBackendOptions,
  updateSubagentSettings,
  type SubagentBackendConfig,
  type SubagentBackendOptions,
} from "@/lib/subagents-api";

type Lang = { zh: string; en: string };

/** The CLI default sentinel — empty model/effort means "let the CLI decide". */
const CUSTOM = "__custom__";

// Defaults mirror BackendConfig in deeptutor/services/subagent/config.py so the
// form shows the same starting state the backend would synthesize.
const DEFAULTS: Required<
  Pick<
    SubagentBackendConfig,
    | "enabled"
    | "model"
    | "effort"
    | "system_prompt"
    | "permission_mode"
    | "sandbox"
    | "approval"
    | "network_access"
    | "ephemeral"
    | "forward_images"
  >
> = {
  enabled: true,
  model: "",
  effort: "",
  system_prompt: "",
  permission_mode: "bypassPermissions",
  sandbox: "workspace-write",
  approval: "never",
  network_access: false,
  ephemeral: false,
  forward_images: false,
};

const PERMISSION_MODES: { value: string; label: Lang }[] = [
  {
    value: "bypassPermissions",
    label: {
      zh: "绕过权限 · 全自主（推荐）",
      en: "Bypass permissions · autonomous (recommended)",
    },
  },
  {
    value: "acceptEdits",
    label: { zh: "自动接受编辑", en: "Accept edits automatically" },
  },
  {
    value: "default",
    label: { zh: "默认 · 可能等待确认", en: "Default · may wait for prompts" },
  },
  {
    value: "plan",
    label: { zh: "计划模式 · 只读", en: "Plan mode · read-only" },
  },
];

const SANDBOXES: { value: string; label: Lang }[] = [
  { value: "read-only", label: { zh: "只读", en: "Read-only" } },
  {
    value: "workspace-write",
    label: { zh: "工作目录可写（推荐）", en: "Workspace write (recommended)" },
  },
  { value: "danger-full-access", label: { zh: "完全访问", en: "Full access" } },
  {
    value: "bypass",
    label: { zh: "绕过沙箱与审批", en: "Bypass sandbox & approvals" },
  },
];

const APPROVALS: { value: string; label: Lang }[] = [
  {
    value: "never",
    label: { zh: "从不询问（推荐）", en: "Never ask (recommended)" },
  },
  { value: "on-failure", label: { zh: "失败时询问", en: "On failure" } },
  { value: "on-request", label: { zh: "按需询问", en: "On request" } },
  {
    value: "untrusted",
    label: { zh: "不可信命令时询问", en: "Untrusted commands" },
  },
];

export function SubagentSettingsEditor({ kind }: { kind: string }) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [options, setOptions] = useState<SubagentBackendOptions | null>(null);
  const [config, setConfig] = useState<SubagentBackendConfig>({ ...DEFAULTS });
  const [customModel, setCustomModel] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const Glyph = agentGlyph(kind);

  const fetchOptions = useCallback(async () => {
    const all = await getBackendOptions();
    return all.find((o) => o.kind === kind) ?? null;
  }, [kind]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [opts, settings] = await Promise.all([
        fetchOptions(),
        getSubagentSettings(),
      ]);
      setOptions(opts);
      const stored = settings.backends?.[kind] ?? {};
      setConfig({ ...DEFAULTS, ...stored });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchOptions, kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      // Actively re-pull this backend's catalog (CC scrapes /model live).
      setOptions(await syncBackendOptions(kind));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }, [kind]);

  // Persist a patch for THIS backend only; the API merges per field, so we send
  // just what changed and never clobber the other backend or unsent fields.
  const save = useCallback(
    async (patch: Partial<SubagentBackendConfig>) => {
      setConfig((prev) => ({ ...prev, ...patch }));
      setBusy(true);
      setError(null);
      try {
        await updateSubagentSettings({ backends: { [kind]: patch } });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [kind],
  );

  const isCodex = kind === "codex";
  const knownSlugs = useMemo(
    () => new Set((options?.models ?? []).map((m) => m.slug)),
    [options],
  );
  const showCustomModel =
    customModel || (config.model !== "" && !knownSlugs.has(config.model ?? ""));

  // Effort choices: per-model for Codex (its cache carries each model's levels),
  // global for Claude Code. Falls back to the backend's union when the chosen
  // model isn't a known slug (custom / default).
  const effortChoices = useMemo(() => {
    if (isCodex && config.model && knownSlugs.has(config.model)) {
      const m = options?.models.find((x) => x.slug === config.model);
      if (m?.efforts?.length) return m.efforts;
    }
    return options?.efforts ?? [];
  }, [isCodex, config.model, knownSlugs, options]);

  const onModelSelect = useCallback(
    (value: string) => {
      if (value === CUSTOM) {
        setCustomModel(true);
        return;
      }
      setCustomModel(false);
      // Reset an effort the newly chosen model doesn't support (Codex).
      const m = options?.models.find((x) => x.slug === value);
      const patch: Partial<SubagentBackendConfig> = { model: value };
      if (
        isCodex &&
        config.effort &&
        m?.efforts?.length &&
        !m.efforts.includes(config.effort)
      ) {
        patch.effort = "";
      }
      void save(patch);
    },
    [options, isCodex, config.effort, save],
  );

  const displayName =
    options?.display_name ?? (isCodex ? "Codex" : "Claude Code");

  return (
    <div>
      <SettingsPageHeader
        title={displayName}
        description={tr({
          zh: `DeepTutor 通过 consult_subagent 调用本机 ${displayName} 时使用的模型、推理强度与运行参数。设置后即覆盖 CLI 的默认值；留空表示沿用 CLI 默认。`,
          en: `Model, reasoning effort, and run parameters DeepTutor drives the local ${displayName} with when consulting it. These override the CLI defaults; leave blank to keep the CLI's own default.`,
        })}
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {tr({ zh: "加载中…", en: "Loading…" })}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && options && (
        <>
          {/* Availability + sync. The model/effort lists change over time, so
              the user can re-pull them on demand. */}
          <SettingSection
            title={tr({ zh: "连接与同步", en: "Connection & sync" })}
            description={tr({
              zh: "供应商会不定期增删模型与推理档位——随时点同步即可重新拉取最新列表。",
              en: "Vendors add and retire models and effort levels over time — sync any time to re-pull the latest lists.",
            })}
          >
            <SettingRow
              title={tr({ zh: "本机状态", en: "On this machine" })}
              description={
                options.available
                  ? options.version
                  : options.detail ||
                    tr({
                      zh: "未在 PATH 上找到该 CLI。",
                      en: "CLI not found on PATH.",
                    })
              }
              control={
                <span
                  className={`inline-flex items-center gap-1.5 text-[12px] ${
                    options.available
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-amber-600 dark:text-amber-400"
                  }`}
                >
                  {Glyph ? <Glyph size={15} /> : null}
                  {options.available ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  {options.available
                    ? tr({ zh: "已安装", en: "Installed" })
                    : tr({ zh: "未检测到", en: "Not detected" })}
                </span>
              }
            />
            <SettingRow
              title={tr({ zh: "模型列表", en: "Model list" })}
              description={
                options.synced_at
                  ? tr({
                      zh: `上次同步：${formatTs(options.synced_at, zh)}`,
                      en: `Last synced: ${formatTs(options.synced_at, zh)}`,
                    })
                  : tr({
                      zh: "该 CLI 无可枚举的模型接口，下方为常用别名，可自定义任意模型名。",
                      en: "This CLI has no model-list API; below are the common aliases, and any model name is accepted.",
                    })
              }
              control={
                <button
                  type="button"
                  disabled={syncing}
                  onClick={() => void sync()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/40 disabled:opacity-60"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`}
                  />
                  {tr({ zh: "同步", en: "Sync" })}
                </button>
              }
            />
          </SettingSection>

          <SettingSection
            title={tr({ zh: "模型", en: "Model" })}
            description={tr({
              zh: "DeepTutor 调用该智能体时使用的模型与推理强度。",
              en: "The model and reasoning effort DeepTutor consults this agent with.",
            })}
          >
            <SettingRow
              title={tr({ zh: "启用", en: "Enabled" })}
              description={tr({
                zh: "关闭后，DeepTutor 不会在对话中调用该智能体。",
                en: "When off, DeepTutor won't consult this agent in chat.",
              })}
              control={
                <Toggle
                  checked={config.enabled !== false}
                  disabled={busy}
                  onChange={(v) => void save({ enabled: v })}
                />
              }
            />
            <SettingRow
              title={tr({ zh: "模型", en: "Model" })}
              control={
                <div className="flex w-[260px] flex-col items-end gap-2">
                  <select
                    className={selectClass}
                    disabled={busy}
                    value={showCustomModel ? CUSTOM : (config.model ?? "")}
                    onChange={(e) => onModelSelect(e.target.value)}
                  >
                    <option value="">
                      {tr({ zh: "CLI 默认", en: "CLI default" })}
                    </option>
                    {options.models.map((m) => (
                      <option key={m.slug} value={m.slug}>
                        {m.display_name}
                      </option>
                    ))}
                    {options.allow_custom_model && (
                      <option value={CUSTOM}>
                        {tr({ zh: "自定义…", en: "Custom…" })}
                      </option>
                    )}
                  </select>
                  {showCustomModel && (
                    <input
                      className={inputClass}
                      disabled={busy}
                      placeholder={tr({
                        zh: "输入模型名",
                        en: "Enter a model name",
                      })}
                      value={config.model ?? ""}
                      onChange={(e) =>
                        setConfig((p) => ({ ...p, model: e.target.value }))
                      }
                      onBlur={(e) =>
                        void save({ model: e.target.value.trim() })
                      }
                    />
                  )}
                </div>
              }
            />
            <SettingRow
              title={tr({ zh: "推理强度", en: "Reasoning effort" })}
              control={
                <select
                  className={`${selectClass} w-[260px]`}
                  disabled={busy || effortChoices.length === 0}
                  value={config.effort ?? ""}
                  onChange={(e) => void save({ effort: e.target.value })}
                >
                  <option value="">
                    {tr({ zh: "CLI 默认", en: "CLI default" })}
                  </option>
                  {effortChoices.map((eff) => (
                    <option key={eff} value={eff}>
                      {eff}
                    </option>
                  ))}
                </select>
              }
            />
          </SettingSection>

          {!isCodex && (
            <SettingSection
              title={tr({ zh: "系统提示", en: "System prompt" })}
              description={tr({
                zh: "追加到该智能体的系统提示（--append-system-prompt）。留空则使用 DeepTutor 的默认委派提示。",
                en: "Appended to the agent's system prompt (--append-system-prompt). Blank uses DeepTutor's default delegate instruction.",
              })}
            >
              <div className="py-4">
                <textarea
                  className={`${inputClass} min-h-[96px] resize-y leading-relaxed`}
                  disabled={busy}
                  placeholder={tr({
                    zh: "（留空使用默认委派提示）",
                    en: "(blank uses the default delegate instruction)",
                  })}
                  value={config.system_prompt ?? ""}
                  onChange={(e) =>
                    setConfig((p) => ({ ...p, system_prompt: e.target.value }))
                  }
                  onBlur={(e) => void save({ system_prompt: e.target.value })}
                />
              </div>
            </SettingSection>
          )}

          <SettingSection
            title={tr({ zh: "运行参数", en: "Run parameters" })}
            description={tr({
              zh: "DeepTutor 无人值守地驱动该智能体——默认值确保它不会卡在等待确认上。",
              en: "DeepTutor drives the agent unattended — the defaults ensure it never stalls waiting for an approval prompt.",
            })}
          >
            {!isCodex && (
              <SettingRow
                title={tr({ zh: "权限模式", en: "Permission mode" })}
                description={tr({
                  zh: "非「绕过权限」的模式可能让无人值守的运行卡住等待确认。",
                  en: "Modes other than bypass may stall an unattended run waiting for a prompt.",
                })}
                control={
                  <select
                    className={`${selectClass} w-[260px]`}
                    disabled={busy}
                    value={config.permission_mode ?? DEFAULTS.permission_mode}
                    onChange={(e) =>
                      void save({ permission_mode: e.target.value })
                    }
                  >
                    {PERMISSION_MODES.map((o) => (
                      <option key={o.value} value={o.value}>
                        {tr(o.label)}
                      </option>
                    ))}
                  </select>
                }
              />
            )}

            {isCodex && (
              <>
                <SettingRow
                  title={tr({ zh: "沙箱", en: "Sandbox" })}
                  control={
                    <select
                      className={`${selectClass} w-[260px]`}
                      disabled={busy}
                      value={config.sandbox ?? DEFAULTS.sandbox}
                      onChange={(e) => void save({ sandbox: e.target.value })}
                    >
                      {SANDBOXES.map((o) => (
                        <option key={o.value} value={o.value}>
                          {tr(o.label)}
                        </option>
                      ))}
                    </select>
                  }
                />
                <SettingRow
                  title={tr({ zh: "审批策略", en: "Approval policy" })}
                  description={tr({
                    zh: "非「从不询问」可能让无人值守的运行卡住。",
                    en: "Anything but never may stall an unattended run.",
                  })}
                  control={
                    <select
                      className={`${selectClass} w-[260px]`}
                      disabled={busy}
                      value={config.approval ?? DEFAULTS.approval}
                      onChange={(e) => void save({ approval: e.target.value })}
                    >
                      {APPROVALS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {tr(o.label)}
                        </option>
                      ))}
                    </select>
                  }
                />
                <SettingRow
                  title={tr({ zh: "命令联网", en: "Command network access" })}
                  description={tr({
                    zh: "允许模型运行的 shell 命令访问网络（工作目录可写模式默认离线）。内置 web search 不受影响。",
                    en: "Let the model's shell commands reach the network (workspace-write is offline by default). The built-in web search is unaffected.",
                  })}
                  control={
                    <Toggle
                      checked={Boolean(config.network_access)}
                      disabled={busy}
                      onChange={(v) => void save({ network_access: v })}
                    />
                  }
                />
                <SettingRow
                  title={tr({ zh: "临时会话", en: "Ephemeral session" })}
                  description={tr({
                    zh: "不在 ~/.codex/sessions 下持久化本次会话。",
                    en: "Don't persist the session under ~/.codex/sessions.",
                  })}
                  control={
                    <Toggle
                      checked={Boolean(config.ephemeral)}
                      disabled={busy}
                      onChange={(v) => void save({ ephemeral: v })}
                    />
                  }
                />
              </>
            )}

            <SettingRow
              title={tr({ zh: "转发图片", en: "Forward images" })}
              description={tr({
                zh: "允许 DeepTutor 把本轮对话中的图片附件转发给该智能体。",
                en: "Let DeepTutor forward image attachments from the chat turn to this agent.",
              })}
              control={
                <Toggle
                  checked={Boolean(config.forward_images)}
                  disabled={busy}
                  onChange={(v) => void save({ forward_images: v })}
                />
              }
            />
          </SettingSection>
        </>
      )}
    </div>
  );
}

function formatTs(value: string, zh: boolean): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(zh ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default SubagentSettingsEditor;
