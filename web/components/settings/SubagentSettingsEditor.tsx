"use client";

import { useSettings } from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { normalizeLanguage } from "@/i18n/languages";
import { formatDate } from "@/lib/datetime";

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
 * e.g. Claude Code / Antigravity / Grok use `permission_mode`, only Codex has its
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
  grok: {
    effort: true,
    systemPrompt: true,
    permissionMode: true,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: false,
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
  grok: "Grok CLI",
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
  grok: {
    zh: "通过 Grok CLI 的 rules 选项传入指令。",
    en: "Additional teaching or delegation instructions are passed through Grok CLI's rules option.",
  },
  claude_code: {
    zh: "通过 --append-system-prompt 追加到系统提示词。",
    en: "Appended to the agent's system prompt (--append-system-prompt).",
  },
  kimi: {
    zh: "指令加在每个 Kimi CLI 新会话的首条消息开头。",
    en: "Kimi CLI has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  },
  opencode: {
    zh: "通过服务端 API 的 system 字段传入每个新会话。",
    en: "Injected into each new session via the server API's system field.",
  },
  mimo: {
    zh: "通过服务器 API 的 system 字段注入到每个新会话。",
    en: "Injected into each new session via the server API's system field.",
  },
  hermes: {
    zh: "指令加在每个 Hermes 新会话的首条消息开头。",
    en: "Hermes has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  },
  hermes_remote: {
    zh: "新建会话或旧会话过期时，通过 Hermes 网关的 instructions 字段传入。",
    en: "Sent through the Hermes gateway API's instructions field for a fresh or expired session.",
  },
  openclaw: {
    zh: "每个新的 OpenClaw 会话密钥首次使用时，指令加在首条消息开头。",
    en: "The instruction is prefixed to the first message for each new OpenClaw session key.",
  },
  deepseek_harness: {
    zh: "指令加在每个 DeepSeek Harness 新会话的首条消息开头。",
    en: "The instruction is prefixed to the first message in each new DeepSeek Harness session.",
  },
};

const PERMISSION_MODES: { value: string; label: Lang }[] = [
  {
    value: "bypassPermissions",
    label: {
      zh: "绕过权限检查（推荐）",
      en: "Bypass permissions · autonomous (recommended)",
    },
  },
  {
    value: "acceptEdits",
    label: { zh: "自动接受编辑", en: "Accept edits automatically" },
  },
  {
    value: "default",
    label: { zh: "默认（可能等待确认）", en: "Default · may wait for prompts" },
  },
  {
    value: "plan",
    label: { zh: "计划模式（只读）", en: "Plan mode · read-only" },
  },
];

const GROK_PERMISSION_MODES: { value: string; label: Lang }[] = [
  {
    value: "dontAsk",
    label: {
      zh: "不询问 · 拒绝需审批操作（默认）",
      en: "Don't ask · deny approval requests (default)",
    },
  },
  {
    value: "plan",
    label: { zh: "计划模式（兼容模式）", en: "Plan (compatibility mode)" },
  },
  {
    value: "default",
    label: { zh: "默认权限", en: "Default permissions" },
  },
  {
    value: "acceptEdits",
    label: { zh: "自动接受编辑", en: "Accept edits automatically" },
  },
  {
    value: "auto",
    label: { zh: "自动评估权限", en: "Automatically evaluate permissions" },
  },
  {
    value: "bypassPermissions",
    label: { zh: "绕过权限", en: "Bypass permissions" },
  },
];

function defaultsForKind(kind: string): typeof DEFAULTS {
  return kind === "grok"
    ? { ...DEFAULTS, permission_mode: "dontAsk" }
    : DEFAULTS;
}

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
    label: { zh: "运行不受信任的命令时询问", en: "Untrusted commands" },
  },
];

export function SubagentSettingsEditor({ kind }: { kind: string }) {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : t(l.en)), [zh, t]);

  const [options, setOptions] = useState<SubagentBackendOptions | null>(null);
  const [liveConfig, setLiveConfig] = useState<SubagentBackendConfig>({
    ...defaultsForKind(kind),
  });
  const [config, setConfig] = useStagedSettings(`subagent:${kind}`, liveConfig, setLiveConfig);
  const [customModel, setCustomModel] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const { applying: busy, draftRevision } = useSettings();
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
      setLiveConfig({ ...defaultsForKind(kind), ...stored });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchOptions, kind]);

  useEffect(() => {
    void load();
  }, [load, draftRevision]);

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

  const save = useCallback(async (patch: Partial<SubagentBackendConfig>) => {
    setConfig((prev) => ({ ...prev, ...patch }));
  }, [setConfig]);

  const features = KIND_FEATURES[kind] ?? FALLBACK_FEATURES;
  const isRemote = kind === "hermes_remote";
  const isGrok = kind === "grok";
  const permissionModes = isGrok ? GROK_PERMISSION_MODES : PERMISSION_MODES;
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
                zh: "通过 HTTP 连接远程 Hermes 网关。",
                en: "Configure the remote Hermes gateway, model, and run parameters DeepTutor uses over HTTP.",
              })
            : t(
                "Model, reasoning effort, and run parameters DeepTutor drives the local {{name}} with when consulting it. These override the CLI defaults; leave blank to keep the CLI's own default.",
                { name: displayName },
              )
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
                    zh: "",
                    en: "Check connectivity and authentication for the configured gateway.",
                  })
                : isGrok
                  ? tr({
                      zh: "检测后端环境中的 Grok CLI。模型和推理强度可手动填写，留空使用 CLI 默认值。",
                      en: "Detect Grok CLI in the backend environment. Leave model and reasoning effort blank for CLI defaults, or enter them manually.",
                    })
                  : tr({
                      zh: "同步可更新模型和推理强度列表。",
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
                isGrok
                  ? tr({
                      zh: "请填写本机 Grok CLI 支持的模型名。同步仅重新检测 CLI。",
                      en: "No model catalog is assumed. Enter a model supported by your Grok CLI; sync only detects the CLI again.",
                    })
                  : options.synced_at
                    ? t("Last synced: {{when}}", {
                        when: formatTs(options.synced_at, i18n.language),
                      })
                    : isRemote
                      ? tr({
                          zh: "网关不提供模型列表。可使用默认模型或手动输入名称。",
                          en: "The remote gateway does not currently enumerate models here; use its default or enter a model name manually.",
                        })
                      : tr({
                          zh: "此 CLI 不提供模型列表。可选择常用别名，也可输入模型名。",
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
                zh: "只保存环境变量名。访问令牌从该变量读取。",
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
                title={tr({ zh: "配置名称", en: "Profile label" })}
                description={tr({
                  zh: "",
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
              zh: "",
              en: "The model and reasoning effort DeepTutor consults this agent with.",
            })}
          >
            <SettingRow
              title={tr({ zh: "启用", en: "Enabled" })}
              description={tr({
                zh: "关闭后，对话中将不再调用此智能体。",
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
                    aria-label={tr({ zh: "模型", en: "Model" })}
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
                      aria-label={tr({ zh: "自定义模型", en: "Custom model" })}
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
                  isGrok ? (
                    <input
                      aria-label={tr({
                        zh: "推理强度",
                        en: "Reasoning effort",
                      })}
                      className={`${inputClass} w-[260px]`}
                      disabled={busy}
                      placeholder={tr({
                        zh: "留空使用 CLI 默认值",
                        en: "Blank uses CLI default",
                      })}
                      value={config.effort ?? ""}
                      onChange={(e) =>
                        setConfig((p) => ({ ...p, effort: e.target.value }))
                      }
                      onBlur={(e) =>
                        void save({ effort: e.target.value.trim() })
                      }
                    />
                  ) : (
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
                  )
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
                zh: "留空使用 DeepTutor 的默认委派指令。",
                en: "Blank uses DeepTutor's default delegate instruction.",
              })}`}
            >
              <div className="py-4">
                <textarea
                  aria-label={tr({ zh: "系统提示", en: "System prompt" })}
                  className={`${inputClass} min-h-[96px] resize-y leading-relaxed`}
                  disabled={busy}
                  placeholder={tr({
                    zh: "留空使用默认指令",
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
              zh: "智能体在后台运行，无法回应交互式确认。",
              en: "DeepTutor drives the agent unattended — the defaults ensure it never stalls waiting for an approval prompt.",
            })}
          >
            {features.permissionMode && (
              <SettingRow
                title={tr({ zh: "权限模式", en: "Permission mode" })}
                description={
                  isGrok
                    ? tr({
                        zh: "默认的 dontAsk 会拒绝需要批准的操作。其他模式遵循 Grok CLI 权限；若要求交互确认，后台任务无法回应。",
                        en: "The default dontAsk mode denies operations that need approval. Other modes follow Grok CLI permissions; unattended runs cannot answer interactive prompts.",
                      })
                    : tr({
                        zh: "后台运行时，其他权限模式可能停下来等待确认。",
                        en: "Modes other than bypass may stall an unattended run waiting for a prompt.",
                      })
                }
                control={
                  <select
                    aria-label={tr({ zh: "权限模式", en: "Permission mode" })}
                    className={`${selectClass} w-[260px]`}
                    disabled={busy}
                    value={
                      config.permission_mode ??
                      defaultsForKind(kind).permission_mode
                    }
                    onChange={(e) =>
                      void save({ permission_mode: e.target.value })
                    }
                  >
                    {permissionModes.map((o) => (
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
                  zh: "开启后自动批准权限请求，关闭后自动拒绝。",
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
                  zh: "实时显示思考过程（--thinking）。",
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
                    zh: "选择其他策略时，后台任务可能停下来等待确认。",
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
                    zh: "允许 shell 命令联网。workspace-write 默认离线，内置搜索不受此项影响。",
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
                    zh: "会话不会保存到 ~/.codex/sessions。",
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
                  zh: "将当前消息的图片附件发给此智能体。",
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

function formatTs(value: string, language: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return formatDate(parsed, normalizeLanguage(language), {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default SubagentSettingsEditor;
