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

/** Empty model/effort means "let the selected runtime decide". */
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
    | "auto_approve"
    | "thinking"
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
  auto_approve: true,
  thinking: true,
  forward_images: false,
};

/**
 * Which knobs each backend kind actually honors — the editor renders from this
 * table instead of per-kind branches. Mirrors what the Python backend reads:
 * e.g. only Claude Code / Antigravity use `permission_mode`, only Codex has its
 * sandbox family, kimi/hermes/opencode/mimo take the `auto_approve` switch.
 */
type KindFeatures = {
  effort: boolean;
  systemPrompt: boolean;
  permissionMode: boolean;
  codexSandbox: boolean;
  autoApprove: boolean;
  thinking: boolean;
  forwardImages: boolean;
};

const KIND_FEATURES: Record<string, KindFeatures> = {
  claude_code: {
    effort: true,
    systemPrompt: true,
    permissionMode: true,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true,
  },
  codex: {
    effort: true,
    systemPrompt: false,
    permissionMode: false,
    codexSandbox: true,
    autoApprove: false,
    thinking: false,
    forwardImages: true,
  },
  antigravity: {
    effort: true, // --effort low|medium|high
    systemPrompt: true,
    permissionMode: true, // permissive modes map onto --dangerously-skip-permissions
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    // Headless `agy` documents no attachment flag; images are named as paths
    // in the prompt for the agent's own file-reading tools instead.
    forwardImages: false,
  },
  kimi: {
    effort: false,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // --yolo
    thinking: true, // --thinking / --no-thinking
    forwardImages: false, // no headless image input
  },
  opencode: {
    effort: true, // --variant
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // permission.asked replies
    thinking: false, // the event bus always streams reasoning
    forwardImages: true, // file parts on the server API
  },
  mimo: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true,
    thinking: false,
    forwardImages: true,
  },
  hermes: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // --yolo
    thinking: false,
    forwardImages: true, // --image
  },
  hermes_remote: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true,
    thinking: false,
    forwardImages: false,
  },
  openclaw: {
    effort: true, // --thinking
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true, // local paths are named in the prompt
  },
  deepseek_harness: {
    effort: true, // SDK reasoning_effort
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true, // local paths are named in the prompt
  },
};

const FALLBACK_FEATURES: KindFeatures = KIND_FEATURES.claude_code;

const DISPLAY_NAMES: Record<string, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
  kimi: "Kimi CLI",
  opencode: "opencode",
  mimo: "MiMo Code",
  hermes: "Hermes Agent",
  hermes_remote: "Hermes Agent (remote)",
  openclaw: "OpenClaw",
  deepseek_harness: "DeepSeek Harness",
};

// Per-kind flavor for the system-prompt section: how the instruction reaches
// the agent (a real flag, a native prompt field, or a first-message prefix).
const SYSTEM_PROMPT_HINT: Record<string, Lang> = {
  claude_code: {
    zh: "追加到该智能体的系统提示（--append-system-prompt）。",
    en: "Appended to the agent's system prompt (--append-system-prompt).",
  },
  kimi: {
    zh: "Kimi CLI 没有系统提示 flag——该指令会前缀在每个新会话的第一条消息上。",
    en: "Kimi CLI has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  },
  opencode: {
    zh: "通过服务器 API 的 system 字段注入到每个新会话。",
    en: "Injected into each new session via the server API's system field.",
  },
  mimo: {
    zh: "通过服务器 API 的 system 字段注入到每个新会话。",
    en: "Injected into each new session via the server API's system field.",
  },
  hermes: {
    zh: "Hermes 没有系统提示 flag——该指令会前缀在每个新会话的第一条消息上。",
    en: "Hermes has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  },
  hermes_remote: {
    zh: "新会话（或远端会话已失效）时，通过 Hermes 网关 API 的 instructions 字段注入。",
    en: "Sent through the Hermes gateway API's instructions field for a fresh or expired session.",
  },
  openclaw: {
    zh: "该指令会前缀在每个新 OpenClaw session key 的第一条消息上。",
    en: "The instruction is prefixed to the first message for each new OpenClaw session key.",
  },
  deepseek_harness: {
    zh: "该指令会前缀在每个新 DeepSeek Harness 会话的第一条消息上。",
    en: "The instruction is prefixed to the first message in each new DeepSeek Harness session.",
  },
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
        // An editor must show what is stored, never a cached copy.
        getSubagentSettings({ force: true }),
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

  const features = KIND_FEATURES[kind] ?? FALLBACK_FEATURES;
  const isRemote = kind === "hermes_remote";
  const knownSlugs = useMemo(
    () => new Set((options?.models ?? []).map((m) => m.slug)),
    [options],
  );
  const showCustomModel =
    customModel || (config.model !== "" && !knownSlugs.has(config.model ?? ""));

  // Effort choices: per-model when the catalog carries each model's levels
  // (Codex, opencode family), else the backend's union (Claude Code). Falls
  // back to the union when the chosen model isn't a known slug.
  const effortChoices = useMemo(() => {
    if (config.model && knownSlugs.has(config.model)) {
      const m = options?.models.find((x) => x.slug === config.model);
      if (m?.efforts?.length) return m.efforts;
    }
    return options?.efforts ?? [];
  }, [config.model, knownSlugs, options]);

  const onModelSelect = useCallback(
    (value: string) => {
      if (value === CUSTOM) {
        setCustomModel(true);
        return;
      }
      setCustomModel(false);
      // Reset an effort the newly chosen model doesn't support.
      const m = options?.models.find((x) => x.slug === value);
      const patch: Partial<SubagentBackendConfig> = { model: value };
      if (
        config.effort &&
        m?.efforts?.length &&
        !m.efforts.includes(config.effort)
      ) {
        patch.effort = "";
      }
      void save(patch);
    },
    [options, config.effort, save],
  );

  const displayName = options?.display_name ?? DISPLAY_NAMES[kind] ?? kind;

  return (
    <div>
      <SettingsPageHeader
        title={displayName}
        description={
          isRemote
            ? tr({
                zh: "配置 DeepTutor 通过 HTTP 调用的远程 Hermes 网关、模型与运行参数。",
                en: "Configure the remote Hermes gateway, model, and run parameters DeepTutor uses over HTTP.",
              })
            : tr({
                zh: `DeepTutor 通过 consult_subagent 调用本机 ${displayName} 时使用的模型、推理强度与运行参数。设置后即覆盖 CLI 的默认值；留空表示沿用 CLI 默认。`,
                en: `Model, reasoning effort, and run parameters DeepTutor drives the local ${displayName} with when consulting it. These override the CLI defaults; leave blank to keep the CLI's own default.`,
              })
        }
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
            description={
              isRemote
                ? tr({
                    zh: "检查已配置网关的连通性与认证状态。",
                    en: "Check connectivity and authentication for the configured gateway.",
                  })
                : tr({
                    zh: "供应商会不定期增删模型与推理档位——随时点同步即可重新拉取最新列表。",
                    en: "Vendors add and retire models and effort levels over time — sync any time to re-pull the latest lists.",
                  })
            }
          >
            <SettingRow
              title={
                isRemote
                  ? tr({ zh: "网关状态", en: "Gateway status" })
                  : tr({ zh: "本机状态", en: "On this machine" })
              }
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
                    ? isRemote
                      ? tr({ zh: "可连接", en: "Reachable" })
                      : tr({ zh: "已安装", en: "Installed" })
                    : isRemote
                      ? tr({ zh: "不可用", en: "Unavailable" })
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
                  : isRemote
                    ? tr({
                        zh: "远程网关当前不提供模型枚举；可以留空使用网关默认值，或手动填写模型名。",
                        en: "The remote gateway does not currently enumerate models here; use its default or enter a model name manually.",
                      })
                    : tr({
                        zh: "该 CLI 无可枚举的模型接口，下方为常用别名，可自定义任意模型名。",
                        en: "This CLI has no model-list API; below are the common aliases, and any model name is accepted.",
                      })
              }
              control={
                isRemote ? (
                  <span className="text-[12px] text-[var(--muted-foreground)]">
                    {tr({ zh: "网关模型由服务端提供", en: "Gateway models are server-managed" })}
                  </span>
                ) : (
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
                )
              }
            />
          </SettingSection>

          {isRemote && (
            <SettingSection
              title={tr({ zh: "远程网关", en: "Remote gateway" })}
              description={tr({
                zh: "密钥只从环境变量读取；这里仅保存变量名，不保存密钥值。",
                en: "The bearer is read only from the environment; this stores the variable name, never the secret.",
              })}
            >
              <SettingRow
                title={tr({ zh: "网关 URL", en: "Gateway URL" })}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.base_url ?? ""}
                    placeholder={tr({
                      zh: "例如：http://hermes-uni:8642",
                      en: "e.g. http://hermes-uni:8642",
                    })}
                    onChange={(e) => setConfig((p) => ({ ...p, base_url: e.target.value }))}
                    onBlur={(e) => void save({ base_url: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={tr({ zh: "密钥环境变量", en: "API key environment variable" })}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.api_key_env ?? "DEEPTUTOR_HERMES_REMOTE_API_KEY"}
                    onChange={(e) => setConfig((p) => ({ ...p, api_key_env: e.target.value }))}
                    onBlur={(e) => void save({ api_key_env: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={tr({ zh: "配置 profile", en: "Profile label" })}
                description={tr({
                  zh: "仅作部署标识，不会把密钥写入设置。",
                  en: "Informational deployment label; it never stores a key.",
                })}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.profile ?? ""}
                    onChange={(e) => setConfig((p) => ({ ...p, profile: e.target.value }))}
                    onBlur={(e) => void save({ profile: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={tr({ zh: "空闲超时（秒）", en: "Idle timeout (seconds)" })}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    type="number"
                    min={1}
                    max={86400}
                    value={config.idle_timeout_seconds ?? 600}
                    onChange={(e) =>
                      setConfig((p) => ({
                        ...p,
                        idle_timeout_seconds: Number.parseInt(e.target.value, 10),
                      }))
                    }
                    onBlur={(e) =>
                      void save({ idle_timeout_seconds: Number.parseInt(e.target.value, 10) })
                    }
                  />
                }
              />
            </SettingSection>
          )}

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
                      {isRemote
                        ? tr({ zh: "网关默认", en: "Gateway default" })
                        : tr({ zh: "CLI 默认", en: "CLI default" })}
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
            {features.effort && (
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
                      {isRemote
                        ? tr({ zh: "网关默认", en: "Gateway default" })
                        : tr({ zh: "CLI 默认", en: "CLI default" })}
                    </option>
                    {effortChoices.map((eff) => (
                      <option key={eff} value={eff}>
                        {eff}
                      </option>
                    ))}
                  </select>
                }
              />
            )}
          </SettingSection>

          {features.systemPrompt && (
            <SettingSection
              title={tr({ zh: "系统提示", en: "System prompt" })}
              description={`${tr(
                SYSTEM_PROMPT_HINT[kind] ?? SYSTEM_PROMPT_HINT.claude_code,
              )} ${tr({
                zh: "留空则使用 DeepTutor 的默认委派提示。",
                en: "Blank uses DeepTutor's default delegate instruction.",
              })}`}
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
            {features.permissionMode && (
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

            {features.autoApprove && (
              <SettingRow
                title={tr({ zh: "自动批准", en: "Auto-approve" })}
                description={tr({
                  zh: "自动批准该智能体的权限请求。关闭后请求将被拒绝——无人值守运行无法交互确认。",
                  en: "Approve the agent's permission asks automatically. When off they are rejected — an unattended run can't confirm interactively.",
                })}
                control={
                  <Toggle
                    checked={config.auto_approve !== false}
                    disabled={busy}
                    onChange={(v) => void save({ auto_approve: v })}
                  />
                }
              />
            )}

            {features.thinking && (
              <SettingRow
                title={tr({ zh: "思考过程", en: "Thinking" })}
                description={tr({
                  zh: "流式展示模型的思考过程（--thinking）。",
                  en: "Stream the model's thinking (--thinking).",
                })}
                control={
                  <Toggle
                    checked={config.thinking !== false}
                    disabled={busy}
                    onChange={(v) => void save({ thinking: v })}
                  />
                }
              />
            )}

            {features.codexSandbox && (
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

            {features.forwardImages && (
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
            )}
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
