"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Eye,
  EyeOff,
  FileText,
  Heart,
  Loader2,
  MessageCircle,
  Pencil,
  Play,
  Plus,
  Save,
  Settings2,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import dynamic from "next/dynamic";
import { apiFetch, apiUrl } from "@/lib/api";
import ModelSelector from "@/components/chat/home/ModelSelector";
import {
  listLLMOptions,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  {
    ssr: false,
  },
);

/* ── Types ──────────────────────────────────────────────── */

interface BotInfo {
  bot_id: string;
  name: string;
  description: string;
  persona: string;
  /**
   * From `GET /tutorbot` (list): channel name keys only — never carries secrets.
   * The single-bot detail endpoint returns a richer dict; ChannelsTab fetches
   * it explicitly via `?include_secrets=true` and works with that shape directly,
   * so this list-shape type is sufficient here.
   */
  channels: string[];
  model: string | null;
  llm_selection?: LLMSelection | null;
  running: boolean;
  started_at: string | null;
  /** Set when a previous PATCH succeeded but `reload_channels` failed. */
  last_reload_error?: string | null;
}

interface SoulTemplate {
  id: string;
  name: string;
  content: string;
}

type Tab = "bots" | "profiles" | "channels" | "souls";

const BOT_FILES = [
  "SOUL.md",
  "USER.md",
  "TOOLS.md",
  "AGENTS.md",
  "HEARTBEAT.md",
] as const;
type BotFile = (typeof BOT_FILES)[number];

/* ── Main Page ──────────────────────────────────────────── */

export default function AgentsPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [bots, setBots] = useState<BotInfo[]>([]);
  const [souls, setSouls] = useState<SoulTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("bots");
  const [toast, setToast] = useState("");
  const [llmOptions, setLLMOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(
    null,
  );
  const [llmOptionsLoading, setLLMOptionsLoading] = useState(true);
  const [llmOptionsError, setLLMOptionsError] = useState(false);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const loadBots = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/tutorbot"));
      const data = await res.json();
      setBots(Array.isArray(data) ? data : (data.bots ?? []));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSouls = useCallback(async () => {
    try {
      const res = await apiFetch(apiUrl("/api/v1/tutorbot/souls"));
      if (res.ok) setSouls(await res.json());
    } catch {
      /* ignore */
    }
  }, []);

  const loadLLMOptions = useCallback(async () => {
    setLLMOptionsLoading(true);
    try {
      const payload = await listLLMOptions();
      setLLMOptions(payload.options);
      setActiveLLMDefault(payload.active);
      setLLMOptionsError(false);
    } catch {
      setLLMOptions([]);
      setActiveLLMDefault(null);
      setLLMOptionsError(true);
    } finally {
      setLLMOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBots();
    void loadSouls();
    void loadLLMOptions();
  }, [loadBots, loadSouls, loadLLMOptions]);

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("TutorBot Agents")}
          </h1>
          {toast ? (
            <p className="mt-1 text-[13px] text-[var(--primary)] animate-fade-in">
              {toast}
            </p>
          ) : (
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Manage your in-process TutorBot instances")}
            </p>
          )}
        </div>

        {/* Tabs */}
        <div className="mb-6 flex items-center gap-1 border-b border-[var(--border)]/50 pb-3">
          {[
            { key: "bots" as Tab, label: t("Bots"), icon: Bot },
            { key: "profiles" as Tab, label: t("Profiles"), icon: FileText },
            { key: "channels" as Tab, label: t("Channels"), icon: Settings2 },
            { key: "souls" as Tab, label: t("Soul Templates"), icon: Heart },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {activeTab === "bots" ? (
          <BotsTab
            bots={bots}
            souls={souls}
            loading={loading}
            llmOptions={llmOptions}
            activeLLMDefault={activeLLMDefault}
            llmOptionsLoading={llmOptionsLoading}
            llmOptionsError={llmOptionsError}
            onReload={loadBots}
            onToast={setToast}
            router={router}
          />
        ) : activeTab === "profiles" ? (
          <ProfilesTab
            bots={bots}
            souls={souls}
            loading={loading}
            onToast={setToast}
            onReloadSouls={loadSouls}
          />
        ) : activeTab === "channels" ? (
          <ChannelsTab
            bots={bots}
            loading={loading}
            onToast={setToast}
            onReload={loadBots}
          />
        ) : (
          <SoulsTab souls={souls} onReload={loadSouls} onToast={setToast} />
        )}
      </div>
    </div>
  );
}

/* ── Channels tab (schema-driven, all channels) ─────────── */

/**
 * JSON-Schema fragment subset we actually consume. Pydantic emits richer
 * shapes (allOf / examples / formats) that we ignore — the form gracefully
 * falls back to a text input for anything it doesn't recognise.
 */
type JsonSchema = {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
};

interface ChannelSchemaEntry {
  name: string;
  display_name: string;
  default_config: Record<string, unknown>;
  secret_fields: string[];
  json_schema: JsonSchema;
}

interface ChannelsSchemaResponse {
  channels: Record<string, ChannelSchemaEntry>;
  global: { json_schema: JsonSchema; secret_fields: string[] };
}

/** Pick the first non-null variant of an `anyOf` and merge its meta. */
function resolveSchemaVariant(s: JsonSchema): JsonSchema {
  if (!s.anyOf) return s;
  const first = s.anyOf.find((v) => v.type !== "null") ?? s.anyOf[0];
  return {
    ...first,
    title: s.title ?? first.title,
    description: s.description ?? first.description,
  };
}

/** True iff this schema's value can be `null` (e.g. `Optional[str]`). */
function isNullable(s: JsonSchema): boolean {
  if (Array.isArray(s.type) && s.type.includes("null")) return true;
  if (s.anyOf?.some((v) => v.type === "null")) return true;
  return false;
}

/** Default value for a property when the live config doesn't set it. */
function defaultFor(s: JsonSchema): unknown {
  if (s.default !== undefined) return s.default;
  const v = resolveSchemaVariant(s);
  switch (v.type) {
    case "boolean":
      return false;
    case "integer":
    case "number":
      return 0;
    case "array":
      return [];
    case "object":
      return {};
    case "string":
    default:
      return "";
  }
}

/** Title-case a snake_case key when no `title` is provided. */
function humaniseKey(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Generic field renderer — recursive for nested objects. */
function SchemaField({
  fieldKey,
  schema,
  value,
  onChange,
  secretFields,
  path,
  showSecretFor,
  toggleSecret,
}: {
  fieldKey: string;
  schema: JsonSchema;
  value: unknown;
  onChange: (next: unknown) => void;
  secretFields: Set<string>;
  path: string;
  showSecretFor: Set<string>;
  toggleSecret: (path: string) => void;
}) {
  const v = resolveSchemaVariant(schema);
  const label = schema.title || v.title || humaniseKey(fieldKey);
  const description = schema.description || v.description;
  const isSecret = secretFields.has(path);
  const enumValues = (v.enum ?? schema.enum) as unknown[] | undefined;

  // Boolean → checkbox row (label inline).
  if (v.type === "boolean") {
    return (
      <label className="flex items-start gap-2 text-[13px]">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          {label}
          {description && (
            <span className="ml-1 text-[11px] text-[var(--muted-foreground)]">
              — {description}
            </span>
          )}
        </span>
      </label>
    );
  }

  // Enum / Literal → select.
  if (Array.isArray(enumValues) && enumValues.length > 0) {
    return (
      <div>
        <FieldLabel label={label} description={description} />
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
        >
          {enumValues.map((opt) => (
            <option key={String(opt)} value={String(opt)}>
              {String(opt)}
            </option>
          ))}
        </select>
      </div>
    );
  }

  // Array of strings → textarea (one per line). For non-string arrays we
  // fall through to JSON editing below.
  if (v.type === "array" && (v.items?.type === "string" || !v.items)) {
    const lines = Array.isArray(value) ? (value as unknown[]).map(String) : [];
    return (
      <div>
        <FieldLabel
          label={label}
          description={description ?? "One value per line"}
        />
        <textarea
          value={lines.join("\n")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
          rows={Math.max(3, Math.min(8, lines.length + 1))}
          className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none focus:border-[var(--ring)]"
        />
      </div>
    );
  }

  // Nested object → recursive fieldset.
  if (v.type === "object" && v.properties) {
    const obj = (value && typeof value === "object" ? value : {}) as Record<
      string,
      unknown
    >;
    return (
      <fieldset className="rounded-lg border border-[var(--border)]/60 px-3 py-2.5 space-y-2.5">
        <legend className="px-1 text-[12px] font-medium text-[var(--muted-foreground)]">
          {label}
        </legend>
        {description && (
          <p className="text-[11px] text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
        {Object.entries(v.properties).map(([k, child]) => (
          <SchemaField
            key={k}
            fieldKey={k}
            schema={child}
            value={obj[k] ?? defaultFor(child)}
            onChange={(next) => onChange({ ...obj, [k]: next })}
            secretFields={secretFields}
            path={path ? `${path}.${k}` : k}
            showSecretFor={showSecretFor}
            toggleSecret={toggleSecret}
          />
        ))}
      </fieldset>
    );
  }

  // Integer/number → number input.
  if (v.type === "integer" || v.type === "number") {
    return (
      <div>
        <FieldLabel label={label} description={description} />
        <input
          type="number"
          value={typeof value === "number" ? value : ""}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") onChange(isNullable(schema) ? null : 0);
            else
              onChange(
                v.type === "integer" ? parseInt(raw, 10) : parseFloat(raw),
              );
          }}
          className="w-40 rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
        />
      </div>
    );
  }

  // Default: string input (with secret reveal handling).
  const reveal = showSecretFor.has(path);
  const strVal = value == null ? "" : String(value);
  return (
    <div>
      <FieldLabel label={label} description={description} />
      <div className="relative">
        <input
          type={isSecret && !reveal ? "password" : "text"}
          autoComplete={isSecret ? "new-password" : "off"}
          spellCheck={!isSecret}
          value={strVal}
          onChange={(e) => {
            const next = e.target.value;
            // Empty optional strings persist as null (matches Pydantic's
            // `Optional[str]` default and avoids "" sneaking past validators).
            onChange(next === "" && isNullable(schema) ? null : next);
          }}
          className={`w-full rounded-lg border border-[var(--border)] bg-transparent py-2 pl-3 ${isSecret ? "pr-10 font-mono" : "pr-3"} text-[13px] outline-none focus:border-[var(--ring)]`}
        />
        {isSecret && (
          <button
            type="button"
            onClick={() => toggleSecret(path)}
            className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label={reveal ? "Hide secret" : "Show secret"}
            title={reveal ? "Hide secret" : "Show secret"}
          >
            {reveal ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}

function FieldLabel({
  label,
  description,
}: {
  label: string;
  description?: string;
}) {
  return (
    <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
      {label}
      {description && (
        <span className="ml-1 font-normal opacity-70">— {description}</span>
      )}
    </label>
  );
}

function ChannelsTab({
  bots,
  loading,
  onToast,
  onReload,
}: {
  bots: BotInfo[];
  loading: boolean;
  onToast: (msg: string) => void;
  onReload: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [selectedBot, setSelectedBot] = useState("");
  const [schemaCatalog, setSchemaCatalog] =
    useState<ChannelsSchemaResponse | null>(null);
  const [channels, setChannels] = useState<Record<string, unknown>>({});
  const [activeChannel, setActiveChannel] = useState<string | null>(null);
  const [reloadError, setReloadError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  /** dot-paths of secrets the user has explicitly toggled to plaintext. */
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  // One-time fetch of the channel schema catalog. Cheap and never changes
  // at runtime (channels are discovered at process start).
  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/tutorbot/channels/schema"));
        if (res.ok) setSchemaCatalog(await res.json());
      } catch {
        /* leave catalog null → renders fallback message */
      }
    })();
  }, []);

  useEffect(() => {
    if (bots.length > 0 && !selectedBot) setSelectedBot(bots[0].bot_id);
  }, [bots, selectedBot]);

  useEffect(() => {
    setRevealed(new Set());
    setReloadError(null);
  }, [selectedBot]);

  const loadDetail = useCallback(async (bid: string) => {
    if (!bid) return;
    setLoadingDetail(true);
    try {
      // Edit form needs raw secrets to populate fields. Default GET masks them.
      const res = await apiFetch(
        apiUrl(`/api/v1/tutorbot/${bid}?include_secrets=true`),
      );
      if (!res.ok) return;
      const data = await res.json();
      const raw = (data.channels ?? {}) as Record<string, unknown>;
      // Surface globals as-is; per-channel dicts are passed straight to the
      // SchemaForm which handles per-field defaults from the JSON schema.
      setChannels({
        send_progress: raw.send_progress !== false,
        send_tool_hints: !!raw.send_tool_hints,
        ...Object.fromEntries(
          Object.entries(raw).filter(
            ([k]) => k !== "send_progress" && k !== "send_tool_hints",
          ),
        ),
      });
      setReloadError(
        typeof data.last_reload_error === "string"
          ? data.last_reload_error
          : null,
      );
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selectedBot) void loadDetail(selectedBot);
  }, [selectedBot, loadDetail]);

  // Pick a sensible default active channel: prefer one already enabled,
  // otherwise the first channel in the catalog.
  useEffect(() => {
    if (activeChannel || !schemaCatalog) return;
    const names = Object.keys(schemaCatalog.channels);
    const enabled = names.find((n) => {
      const cfg = channels[n];
      return (
        cfg &&
        typeof cfg === "object" &&
        (cfg as Record<string, unknown>).enabled === true
      );
    });
    setActiveChannel(enabled ?? names[0] ?? null);
  }, [schemaCatalog, channels, activeChannel]);

  const toggleSecret = useCallback((path: string) => {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const setActiveChannelConfig = (next: unknown) => {
    if (!activeChannel) return;
    setChannels((prev) => ({ ...prev, [activeChannel]: next }));
  };

  const save = async () => {
    if (!selectedBot) return;
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/tutorbot/${selectedBot}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channels }),
      });
      if (res.ok) {
        onToast(t("Channels saved"));
        await Promise.all([onReload(), loadDetail(selectedBot)]);
      } else if (res.status === 422) {
        const err = (await res.json().catch(() => ({}))) as {
          detail?: { message?: string; errors?: unknown } | string;
        };
        const detail = err.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : (detail?.message ?? t("Invalid channel configuration"));
        onToast(msg);
      } else {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        onToast(err.detail ?? t("Save failed"));
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (bots.length === 0) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
        <p className="text-[14px] font-medium text-[var(--foreground)]">
          {t("No bots to configure")}
        </p>
        <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
          {t("Create a bot first in the Bots tab.")}
        </p>
      </div>
    );
  }

  const channelEntries = schemaCatalog
    ? Object.entries(schemaCatalog.channels).sort(([, a], [, b]) =>
        a.display_name.localeCompare(b.display_name),
      )
    : [];
  const activeEntry = activeChannel
    ? schemaCatalog?.channels[activeChannel]
    : undefined;
  const activeValue =
    activeChannel &&
    channels[activeChannel] &&
    typeof channels[activeChannel] === "object"
      ? (channels[activeChannel] as Record<string, unknown>)
      : (activeEntry?.default_config ?? {});
  const activeSecretSet = new Set(activeEntry?.secret_fields ?? []);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-[12px] font-medium text-[var(--muted-foreground)] shrink-0">
          {t("Bot")}
        </label>
        <select
          value={selectedBot}
          onChange={(e) => setSelectedBot(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
        >
          {bots.map((b) => (
            <option key={b.bot_id} value={b.bot_id}>
              {b.name} ({b.bot_id})
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || loadingDetail}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {t("Save")}
        </button>
      </div>

      {reloadError && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-300">
          <strong className="font-medium">
            {t("Channel listeners failed to restart:")}
          </strong>{" "}
          <span className="font-mono">{reloadError}</span>{" "}
          <span className="opacity-80">
            {t("Config is saved on disk; stop and start the bot to apply.")}
          </span>
        </div>
      )}

      {loadingDetail || !schemaCatalog ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : (
        <>
          {/* Globals (Delivery) */}
          <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
            <h3 className="text-[13px] font-medium text-[var(--foreground)]">
              {t("Delivery")}
            </h3>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!channels.send_progress}
                onChange={(e) =>
                  setChannels((c) => ({
                    ...c,
                    send_progress: e.target.checked,
                  }))
                }
              />
              {t("Stream progress text to channels")}
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!channels.send_tool_hints}
                onChange={(e) =>
                  setChannels((c) => ({
                    ...c,
                    send_tool_hints: e.target.checked,
                  }))
                }
              />
              {t("Stream tool hints to channels")}
            </label>
          </div>

          {/* Channel master-detail */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-[180px_1fr]">
            <aside className="rounded-xl border border-[var(--border)] p-2 h-fit">
              <ul className="space-y-0.5">
                {channelEntries.map(([name, entry]) => {
                  const cfg = channels[name] as
                    | Record<string, unknown>
                    | undefined;
                  const enabled = cfg?.enabled === true;
                  const isActive = activeChannel === name;
                  return (
                    <li key={name}>
                      <button
                        type="button"
                        onClick={() => setActiveChannel(name)}
                        className={`group flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors ${
                          isActive
                            ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                            : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        <span className="truncate">{entry.display_name}</span>
                        {enabled && (
                          <span
                            aria-label={t("Enabled")}
                            title={t("Enabled")}
                            className="ml-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500"
                          />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </aside>

            <section className="rounded-xl border border-[var(--border)] p-4 space-y-3">
              {!activeEntry ? (
                <p className="text-[13px] text-[var(--muted-foreground)]">
                  {t("Select a channel.")}
                </p>
              ) : (
                <>
                  <div className="flex items-baseline justify-between">
                    <h3 className="text-[14px] font-medium text-[var(--foreground)]">
                      {activeEntry.display_name}
                    </h3>
                    <code className="text-[11px] text-[var(--muted-foreground)]">
                      {activeEntry.name}
                    </code>
                  </div>
                  {activeEntry.json_schema.description && (
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {activeEntry.json_schema.description}
                    </p>
                  )}
                  {Object.entries(activeEntry.json_schema.properties ?? {}).map(
                    ([k, child]) => (
                      <SchemaField
                        key={k}
                        fieldKey={k}
                        schema={child}
                        value={activeValue[k] ?? defaultFor(child)}
                        onChange={(next) =>
                          setActiveChannelConfig({ ...activeValue, [k]: next })
                        }
                        secretFields={activeSecretSet}
                        path={k}
                        showSecretFor={revealed}
                        toggleSecret={toggleSecret}
                      />
                    ),
                  )}
                </>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Bots Tab ───────────────────────────────────────────── */

function BotsTab({
  bots,
  souls,
  loading,
  llmOptions,
  activeLLMDefault,
  llmOptionsLoading,
  llmOptionsError,
  onReload,
  onToast,
  router,
}: {
  bots: BotInfo[];
  souls: SoulTemplate[];
  loading: boolean;
  llmOptions: LLMOption[];
  activeLLMDefault: LLMSelection | null;
  llmOptionsLoading: boolean;
  llmOptionsError: boolean;
  onReload: () => Promise<void>;
  onToast: (msg: string) => void;
  router: ReturnType<typeof useRouter>;
}) {
  const { t } = useTranslation();
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);

  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formSoulId, setFormSoulId] = useState("_custom");
  const [formSoul, setFormSoul] = useState("");
  const [formLLMSelection, setFormLLMSelection] = useState<LLMSelection | null>(
    null,
  );
  const [updatingModelBot, setUpdatingModelBot] = useState<string | null>(null);

  const resetForm = () => {
    setFormName("");
    setFormDesc("");
    setFormSoulId("_custom");
    setFormSoul("");
    setFormLLMSelection(null);
  };

  const botId = useMemo(() => {
    const trimmed = formName.trim();
    if (!trimmed) return "";
    const slug = trimmed
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    if (slug) return slug;
    // Name has no ASCII alphanumerics (e.g. pure Chinese / Japanese).
    // Derive a deterministic ASCII fallback so the bot ID stays
    // filesystem- and URL-safe while the display name keeps its CJK form.
    let h = 0;
    for (let i = 0; i < trimmed.length; i++) {
      h = (h << 5) - h + trimmed.charCodeAt(i);
      h |= 0;
    }
    return `bot-${Math.abs(h).toString(36).padStart(6, "0").slice(0, 8)}`;
  }, [formName]);

  const selectSoul = (id: string) => {
    setFormSoulId(id);
    if (id !== "_custom") {
      const soul = souls.find((s) => s.id === id);
      if (soul) setFormSoul(soul.content);
    }
  };

  const createBot = useCallback(async () => {
    if (!botId) return;
    setCreating(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/tutorbot"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_id: botId,
          name: formName.trim(),
          description: formDesc.trim(),
          persona: formSoul.trim(),
          llm_selection: formLLMSelection,
        }),
      });
      if (res.ok) {
        onToast(`${formName.trim()} created`);
        setShowCreate(false);
        resetForm();
        await onReload();
      } else {
        const err = (await res.json().catch(() => ({}))) as {
          detail?: string | { message?: string };
        };
        const detail =
          typeof err.detail === "string"
            ? err.detail
            : (err.detail?.message ?? t("Failed to create bot"));
        onToast(detail);
      }
    } catch {
      onToast(t("Failed to create bot"));
    } finally {
      setCreating(false);
    }
  }, [
    botId,
    formName,
    formDesc,
    formSoul,
    formLLMSelection,
    onReload,
    onToast,
    t,
  ]);

  const updateBotModel = useCallback(
    async (bid: string, selection: LLMSelection | null) => {
      setUpdatingModelBot(bid);
      try {
        const res = await apiFetch(apiUrl(`/api/v1/tutorbot/${bid}`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            llm_selection: selection,
            ...(selection ? {} : { model: "" }),
          }),
        });
        if (res.ok) {
          onToast(t("Model saved"));
          await onReload();
        } else {
          const err = (await res.json().catch(() => ({}))) as {
            detail?: string;
          };
          onToast(err.detail ?? t("Failed to save model"));
        }
      } catch {
        onToast(t("Failed to save model"));
      } finally {
        setUpdatingModelBot(null);
      }
    },
    [onReload, onToast, t],
  );

  const modelLabelFor = useCallback(
    (bot: BotInfo) => {
      const selected = bot.llm_selection
        ? llmOptions.find((option) =>
            sameLLMSelection(option, bot.llm_selection),
          )
        : null;
      if (selected) return selected.model_name || selected.model;
      if (bot.llm_selection) return t("Selected model");
      if (bot.model) return bot.model;
      return t("System default");
    },
    [llmOptions, t],
  );

  const startBot = useCallback(
    async (bid: string) => {
      const res = await apiFetch(apiUrl("/api/v1/tutorbot"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_id: bid }),
      });
      if (res.ok) {
        onToast(`${bid} started`);
        await onReload();
      }
    },
    [onReload, onToast],
  );

  const stopBot = useCallback(
    async (bid: string) => {
      const res = await apiFetch(apiUrl(`/api/v1/tutorbot/${bid}`), {
        method: "DELETE",
      });
      if (res.ok) {
        onToast(`${bid} stopped`);
        await onReload();
      }
    },
    [onReload, onToast],
  );

  const destroyBot = useCallback(
    async (bid: string, name: string) => {
      if (
        !window.confirm(
          t('Permanently delete "{{name}}" ({{id}})? This cannot be undone.', {
            name,
            id: bid,
          }),
        )
      )
        return;
      const res = await apiFetch(apiUrl(`/api/v1/tutorbot/${bid}/destroy`), {
        method: "DELETE",
      });
      if (res.ok) {
        onToast(`${name} deleted`);
        await onReload();
      }
    },
    [onReload, onToast, t],
  );

  return (
    <>
      {/* New Bot button */}
      <div className="mb-4 flex justify-end">
        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
        >
          <Plus className="h-3 w-3" />
          {t("New Bot")}
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="mb-6 rounded-xl border border-[var(--border)] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[15px] font-medium text-[var(--foreground)]">
              {t("Create TutorBot")}
            </h2>
            <button
              onClick={() => {
                setShowCreate(false);
                resetForm();
              }}
              className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Name")}
              </label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder={t("e.g. Math Tutor")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              {botId && (
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  ID: {botId}
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Description")}{" "}
                <span className="font-normal opacity-60">
                  {t("(optional)")}
                </span>
              </label>
              <input
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                placeholder={t("A brief description of what this bot does")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Soul")}
              </label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                <button
                  onClick={() => selectSoul("_custom")}
                  className={`rounded-md px-2.5 py-1 text-[12px] transition-colors ${
                    formSoulId === "_custom"
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {t("Custom")}
                </button>
                {souls.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => selectSoul(s.id)}
                    className={`rounded-md px-2.5 py-1 text-[12px] transition-colors ${
                      formSoulId === s.id
                        ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                        : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
              <textarea
                value={formSoul}
                onChange={(e) => {
                  setFormSoul(e.target.value);
                  setFormSoulId("_custom");
                }}
                placeholder={t(
                  "Define the bot's personality, values, and communication style in markdown...",
                )}
                rows={8}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] leading-6 text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/60">
                {t(
                  "Pick a soul from the library above, or write your own. Manage the library in the Souls tab.",
                )}
              </p>
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Model")}{" "}
                <span className="font-normal opacity-60">
                  {t("(optional)")}
                </span>
              </label>
              <ModelSelector
                options={llmOptions}
                activeDefault={activeLLMDefault}
                value={formLLMSelection}
                loading={llmOptionsLoading}
                error={llmOptionsError}
                allowSystemDefault
                helperText={t("Applies to this TutorBot")}
                placement="bottom"
                onChange={setFormLLMSelection}
              />
              <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/60">
                {t(
                  "Choose a configured Settings model, or keep the system default.",
                )}
              </p>
            </div>
            <div className="flex justify-end">
              <button
                onClick={createBot}
                disabled={creating || !botId}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {creating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                {t("Create & Start")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bot list */}
      {loading ? (
        <div className="flex min-h-[320px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : bots.length === 0 ? (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
            <Bot size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No TutorBots yet")}
          </p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
            {t("Create your first TutorBot to get started.")}
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {bots.map((bot) => (
            <div
              key={bot.bot_id}
              className="flex items-center justify-between rounded-xl border border-[var(--border)] px-5 py-4 transition-colors hover:border-[var(--border)]"
            >
              <div className="flex items-center gap-4 min-w-0">
                <div
                  className={`h-2 w-2 shrink-0 rounded-full ${bot.running ? "bg-emerald-500" : "bg-[var(--muted-foreground)]/30"}`}
                />
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-[var(--foreground)] truncate">
                    {bot.name}
                  </p>
                  <div className="mt-0.5 flex items-center gap-3 text-[12px] text-[var(--muted-foreground)]">
                    {bot.description ? (
                      <span className="truncate max-w-[300px]">
                        {bot.description}
                      </span>
                    ) : (
                      <span>{bot.bot_id}</span>
                    )}
                    <span>· {modelLabelFor(bot)}</span>
                    {bot.started_at && (
                      <span>
                        ·{" "}
                        {t("started {{time}}", {
                          time: new Date(bot.started_at).toLocaleString(),
                        })}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <ModelSelector
                  options={llmOptions}
                  activeDefault={activeLLMDefault}
                  value={bot.llm_selection ?? null}
                  loading={llmOptionsLoading || updatingModelBot === bot.bot_id}
                  error={llmOptionsError}
                  allowSystemDefault
                  helperText={t("Applies to this TutorBot")}
                  placement="bottom"
                  onChange={(selection) =>
                    updateBotModel(bot.bot_id, selection)
                  }
                />
                {bot.running ? (
                  <>
                    <button
                      onClick={() => router.push(`/agents/${bot.bot_id}/chat`)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--primary)] transition-colors hover:border-[var(--primary)]/50"
                    >
                      <MessageCircle className="h-3 w-3" />
                      {t("Chat")}
                    </button>
                    <button
                      onClick={() => stopBot(bot.bot_id)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-red-400 transition-colors hover:border-red-400/50"
                    >
                      <Square className="h-3 w-3" />
                      {t("Stop")}
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => startBot(bot.bot_id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                  >
                    <Play className="h-3 w-3" />
                    {t("Start")}
                  </button>
                )}
                <button
                  onClick={() => destroyBot(bot.bot_id, bot.name)}
                  className="inline-flex items-center justify-center rounded-lg border border-[var(--border)]/50 p-1.5 text-[var(--muted-foreground)]/50 transition-colors hover:border-red-400/50 hover:text-red-400"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ── Profiles Tab ───────────────────────────────────────── */

function ProfilesTab({
  bots,
  souls,
  loading,
  onToast,
  onReloadSouls,
}: {
  bots: BotInfo[];
  souls: SoulTemplate[];
  loading: boolean;
  onToast: (msg: string) => void;
  onReloadSouls: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [selectedBot, setSelectedBot] = useState<string>("");
  const [activeFile, setActiveFile] = useState<BotFile>("SOUL.md");
  const [files, setFiles] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState("");
  const [selectedSoulId, setSelectedSoulId] = useState("_custom");
  const [sourceSoulId, setSourceSoulId] = useState<string | null>(null);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [saveMode, setSaveMode] = useState<
    "file_only" | "update_template" | "new_template"
  >("file_only");
  const [newTemplateName, setNewTemplateName] = useState("");
  const [replaceModalOpen, setReplaceModalOpen] = useState(false);
  const [pendingSoulId, setPendingSoulId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"edit" | "preview">("edit");

  const hasChanges = editor !== (files[activeFile] ?? "");
  const activeSoulTemplate = useMemo(
    () => souls.find((s) => s.id === selectedSoulId) ?? null,
    [souls, selectedSoulId],
  );
  const sourceSoulTemplate = useMemo(
    () => souls.find((s) => s.id === sourceSoulId) ?? null,
    [souls, sourceSoulId],
  );

  const matchSoulId = useCallback(
    (content: string): string =>
      souls.find((s) => s.content === content)?.id ?? "_custom",
    [souls],
  );

  useEffect(() => {
    if (bots.length > 0 && !selectedBot) {
      setSelectedBot(bots[0].bot_id);
    }
  }, [bots, selectedBot]);

  const loadFiles = useCallback(
    async (bid: string) => {
      if (!bid) return;
      setLoadingFiles(true);
      try {
        const res = await apiFetch(apiUrl(`/api/v1/tutorbot/${bid}/files`));
        const data: Record<string, string> = await res.json();
        setFiles(data);
        setEditor(data[activeFile] ?? "");
        const matched = matchSoulId(data["SOUL.md"] ?? "");
        setSelectedSoulId(matched);
        setSourceSoulId(matched === "_custom" ? null : matched);
      } finally {
        setLoadingFiles(false);
      }
    },
    [activeFile, matchSoulId],
  );

  useEffect(() => {
    if (selectedBot) void loadFiles(selectedBot);
  }, [selectedBot, loadFiles]);

  useEffect(() => {
    setEditor(files[activeFile] ?? "");
    if (activeFile === "SOUL.md") {
      const matched = matchSoulId(files["SOUL.md"] ?? "");
      setSelectedSoulId(matched);
      setSourceSoulId(matched === "_custom" ? null : matched);
    }
    setActiveView("edit");
  }, [activeFile, files, matchSoulId]);

  const applySoulSelection = useCallback(
    (nextId: string) => {
      if (nextId === "_custom") {
        setSelectedSoulId("_custom");
        setSourceSoulId(null);
        return;
      }
      const soul = souls.find((s) => s.id === nextId);
      if (!soul) return;
      setSelectedSoulId(nextId);
      setSourceSoulId(nextId);
      setEditor(soul.content);
    },
    [souls],
  );

  const handleSoulSelect = useCallback(
    (nextId: string) => {
      if (hasChanges) {
        setPendingSoulId(nextId);
        setReplaceModalOpen(true);
        return;
      }
      applySoulSelection(nextId);
    },
    [applySoulSelection, hasChanges],
  );

  const saveFile = useCallback(
    async (
      mode: "file_only" | "update_template" | "new_template",
      createTemplateName?: string,
    ) => {
      if (!selectedBot) return false;
      setSaving(true);
      try {
        if (activeFile === "SOUL.md") {
          const content = editor.trim();
          if (!content) {
            onToast(t("SOUL.md is empty"));
            return false;
          }
          if (mode === "update_template") {
            if (!sourceSoulTemplate) {
              onToast(t("No template selected to update"));
              return false;
            }
            const tplRes = await apiFetch(
              apiUrl(`/api/v1/tutorbot/souls/${sourceSoulTemplate.id}`),
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  name: sourceSoulTemplate.name,
                  content: editor,
                }),
              },
            );
            if (!tplRes.ok) {
              onToast(t("Failed to update soul template"));
              return false;
            }
            await onReloadSouls();
            setSelectedSoulId(sourceSoulTemplate.id);
            setSourceSoulId(sourceSoulTemplate.id);
          } else if (mode === "new_template") {
            const rawName = (createTemplateName ?? "").trim();
            if (!rawName) {
              onToast(t("Template name is required"));
              return false;
            }
            const baseId = rawName
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, "-")
              .replace(/^-|-$/g, "");
            if (!baseId) {
              onToast(t("Please choose a name with letters or numbers"));
              return false;
            }
            const existing = new Set(souls.map((s) => s.id));
            let soulId = baseId;
            let n = 2;
            while (existing.has(soulId)) {
              soulId = `${baseId}-${n}`;
              n += 1;
            }
            const tplRes = await apiFetch(apiUrl("/api/v1/tutorbot/souls"), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                id: soulId,
                name: rawName,
                content: editor,
              }),
            });
            if (tplRes.status === 409) {
              onToast(
                t("A soul with this id already exists, try another name"),
              );
              return false;
            }
            if (!tplRes.ok) {
              onToast(t("Failed to save soul template"));
              return false;
            }
            await onReloadSouls();
            setSelectedSoulId(soulId);
            setSourceSoulId(soulId);
          }
        }

        const res = await apiFetch(
          apiUrl(`/api/v1/tutorbot/${selectedBot}/files/${activeFile}`),
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: editor }),
          },
        );
        if (res.ok) {
          setFiles((prev) => ({ ...prev, [activeFile]: editor }));
          if (activeFile === "SOUL.md") {
            const personaRes = await apiFetch(
              apiUrl(`/api/v1/tutorbot/${selectedBot}`),
              {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ persona: editor }),
              },
            );
            if (!personaRes.ok) {
              onToast(t("SOUL.md saved, but persona sync failed"));
              return false;
            }
          }
          onToast(`${activeFile} saved`);
          return true;
        }
        return false;
      } finally {
        setSaving(false);
      }
    },
    [
      selectedBot,
      activeFile,
      editor,
      onToast,
      onReloadSouls,
      sourceSoulTemplate,
      souls,
      t,
    ],
  );

  const handleSaveClick = useCallback(() => {
    if (activeFile !== "SOUL.md") {
      void saveFile("file_only");
      return;
    }
    setSaveMode(sourceSoulTemplate ? "update_template" : "file_only");
    setNewTemplateName(`${selectedBot || "custom"} soul`);
    setSaveModalOpen(true);
  }, [activeFile, saveFile, selectedBot, sourceSoulTemplate]);

  const handleConfirmSave = useCallback(async () => {
    const ok = await saveFile(saveMode, newTemplateName);
    if (ok) setSaveModalOpen(false);
  }, [newTemplateName, saveFile, saveMode]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSaveClick();
      }
    },
    [handleSaveClick],
  );

  if (loading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (bots.length === 0) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
        <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
          <FileText size={18} />
        </div>
        <p className="text-[14px] font-medium text-[var(--foreground)]">
          {t("No bots to configure")}
        </p>
        <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
          {t("Create a bot first in the Bots tab.")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Bot selector */}
      <div className="flex items-center gap-3">
        <label className="text-[12px] font-medium text-[var(--muted-foreground)] shrink-0">
          {t("Bot")}
        </label>
        <select
          value={selectedBot}
          onChange={(e) => setSelectedBot(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
        >
          {bots.map((b) => (
            <option key={b.bot_id} value={b.bot_id}>
              {b.name} ({b.bot_id})
            </option>
          ))}
        </select>
      </div>

      {/* File tabs */}
      <div className="flex items-center gap-1 border-b border-[var(--border)]/50 pb-2">
        {BOT_FILES.map((fn) => (
          <button
            key={fn}
            onClick={() => setActiveFile(fn)}
            className={`rounded-lg px-2.5 py-1 text-[12px] transition-colors ${
              activeFile === fn
                ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {fn.replace(".md", "")}
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {(["edit", "preview"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setActiveView(v)}
              className={`rounded-lg px-3 py-1.5 text-[12px] transition-colors ${
                activeView === v
                  ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {v === "edit" ? t("Edit") : t("Preview")}
            </button>
          ))}
          {activeFile === "SOUL.md" && (
            <>
              <select
                value={selectedSoulId}
                onChange={(e) => handleSoulSelect(e.target.value)}
                className="rounded-lg border border-[var(--border)] bg-transparent px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              >
                <option value="_custom">{t("Custom")}</option>
                {souls.map((soul) => (
                  <option key={soul.id} value={soul.id}>
                    {soul.name}
                  </option>
                ))}
              </select>
              {activeSoulTemplate && (
                <span className="text-[11px] text-[var(--muted-foreground)]/70">
                  {hasChanges
                    ? t('Editing template "{{name}}"', {
                        name: activeSoulTemplate.name,
                      })
                    : t('Using "{{name}}"', { name: activeSoulTemplate.name })}
                </span>
              )}
              {!activeSoulTemplate && (
                <span className="text-[11px] text-[var(--muted-foreground)]/70">
                  {t("Custom soul")}
                </span>
              )}
            </>
          )}
        </div>
        <button
          onClick={handleSaveClick}
          disabled={saving || !hasChanges}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-40 ${
            hasChanges
              ? "bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90"
              : "border border-[var(--border)]/50 text-[var(--muted-foreground)]"
          }`}
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          {t("Save")}
        </button>
      </div>

      {/* Editor / Preview */}
      {loadingFiles ? (
        <div className="flex min-h-[400px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : activeView === "edit" ? (
        <div>
          <textarea
            value={editor}
            onChange={(e) => {
              const next = e.target.value;
              setEditor(next);
            }}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            className="min-h-[420px] w-full resize-none rounded-xl border border-[var(--border)] bg-transparent px-5 py-4 font-mono text-[13px] leading-7 text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
            placeholder={t("Edit {{file}}...", { file: activeFile })}
          />
          <p className="mt-2 text-[11px] text-[var(--muted-foreground)]/40">
            {t("Cmd+S to save · Markdown supported")}
            {hasChanges && ` · ${t("Unsaved changes")}`}
          </p>
        </div>
      ) : editor.trim() ? (
        <div className="rounded-xl border border-[var(--border)] px-6 py-5">
          <MarkdownRenderer
            content={editor}
            variant="prose"
            className="text-[14px] leading-relaxed"
          />
        </div>
      ) : (
        <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("{{file}} is empty", { file: activeFile })}
          </p>
          <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
            {t("Switch to Edit to add content.")}
          </p>
        </div>
      )}
      {saveModalOpen && activeFile === "SOUL.md" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-xl">
            <h3 className="text-[15px] font-medium text-[var(--foreground)]">
              {t("Save SOUL.md")}
            </h3>
            <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
              {t(
                "Choose whether to only save this bot profile, overwrite the selected template, or save your edits as a new template.",
              )}
            </p>

            <div className="mt-4 space-y-2">
              <label className="flex items-center gap-2 text-[12px] text-[var(--foreground)]">
                <input
                  type="radio"
                  name="save-mode"
                  checked={saveMode === "file_only"}
                  onChange={() => setSaveMode("file_only")}
                />
                {t("Save profile only")}
              </label>
              {sourceSoulTemplate && (
                <label className="flex items-center gap-2 text-[12px] text-[var(--foreground)]">
                  <input
                    type="radio"
                    name="save-mode"
                    checked={saveMode === "update_template"}
                    onChange={() => setSaveMode("update_template")}
                  />
                  {t('Save and overwrite template "{{name}}"', {
                    name: sourceSoulTemplate.name,
                  })}
                </label>
              )}
              <label className="flex items-center gap-2 text-[12px] text-[var(--foreground)]">
                <input
                  type="radio"
                  name="save-mode"
                  checked={saveMode === "new_template"}
                  onChange={() => setSaveMode("new_template")}
                />
                {t("Save and create new template")}
              </label>
            </div>

            {saveMode === "new_template" && (
              <div className="mt-4">
                <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                  {t("Template name")}
                </label>
                <input
                  value={newTemplateName}
                  onChange={(e) => setNewTemplateName(e.target.value)}
                  placeholder={t("e.g. IELTS Mentor")}
                  className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
                />
              </div>
            )}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setSaveModalOpen(false)}
                disabled={saving}
                className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={handleConfirmSave}
                disabled={
                  saving ||
                  (saveMode === "new_template" && !newTemplateName.trim())
                }
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {saving ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Save className="h-3 w-3" />
                )}
                {saveMode === "update_template"
                  ? t("Save and overwrite")
                  : saveMode === "new_template"
                    ? t("Save and create")
                    : t("Save profile")}
              </button>
            </div>
          </div>
        </div>
      )}
      {replaceModalOpen && activeFile === "SOUL.md" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-xl">
            <h3 className="text-[15px] font-medium text-[var(--foreground)]">
              {t("Replace SOUL.md content?")}
            </h3>
            <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
              {t(
                "You have unsaved changes. Switching templates will replace the current editor content.",
              )}
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => {
                  setReplaceModalOpen(false);
                  setPendingSoulId(null);
                }}
                className="rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={() => {
                  if (pendingSoulId) applySoulSelection(pendingSoulId);
                  setReplaceModalOpen(false);
                  setPendingSoulId(null);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
              >
                {t("Replace")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Souls Tab ──────────────────────────────────────────── */

function SoulsTab({
  souls,
  onReload,
  onToast,
}: {
  souls: SoulTemplate[];
  onReload: () => Promise<void>;
  onToast: (msg: string) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);

  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("");
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");

  const startEdit = (soul: SoulTemplate) => {
    setEditing(soul.id);
    setEditName(soul.name);
    setEditContent(soul.content);
    setCreating(false);
  };

  const cancelEdit = () => {
    setEditing(null);
    setEditName("");
    setEditContent("");
  };

  const startCreate = () => {
    setCreating(true);
    setEditing(null);
    setNewName("");
    setNewContent("");
  };

  const saveSoul = useCallback(async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/tutorbot/souls/${editing}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName.trim(), content: editContent }),
      });
      if (res.ok) {
        onToast(`"${editName.trim()}" updated`);
        cancelEdit();
        await onReload();
      }
    } finally {
      setSaving(false);
    }
  }, [editing, editName, editContent, onReload, onToast]);

  const createSoul = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;
    const id = name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    if (!id) return;
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/tutorbot/souls"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, name, content: newContent }),
      });
      if (res.ok) {
        onToast(`"${name}" created`);
        setCreating(false);
        setNewName("");
        setNewContent("");
        await onReload();
      } else if (res.status === 409) {
        onToast(`Soul ID "${id}" already exists`);
      }
    } finally {
      setSaving(false);
    }
  }, [newName, newContent, onReload, onToast]);

  const deleteSoul = useCallback(
    async (soul: SoulTemplate) => {
      if (!window.confirm(t('Delete soul "{{name}}"?', { name: soul.name })))
        return;
      const res = await apiFetch(apiUrl(`/api/v1/tutorbot/souls/${soul.id}`), {
        method: "DELETE",
      });
      if (res.ok) {
        if (editing === soul.id) cancelEdit();
        onToast(`"${soul.name}" deleted`);
        await onReload();
      }
    },
    [editing, onReload, onToast, t],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>, save: () => void) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        save();
      }
    },
    [],
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-[var(--muted-foreground)]">
          {t("Reusable soul templates for creating TutorBots.")}
        </p>
        <button
          onClick={startCreate}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
        >
          <Plus className="h-3 w-3" />
          {t("New Soul")}
        </button>
      </div>

      {/* Create form */}
      {creating && (
        <div className="rounded-xl border border-[var(--border)] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-[15px] font-medium text-[var(--foreground)]">
              {t("New Soul")}
            </h2>
            <button
              onClick={() => setCreating(false)}
              className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Name")}
              </label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t("e.g. Creative Writer")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              {newName.trim() && (
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  ID:{" "}
                  {newName
                    .trim()
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/^-|-$/g, "")}
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                {t("Content")}
              </label>
              <textarea
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                onKeyDown={(e) => handleKeyDown(e, createSoul)}
                placeholder={t("Define the soul in markdown...")}
                rows={10}
                spellCheck={false}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] leading-6 text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setCreating(false)}
                className="rounded-lg px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={createSoul}
                disabled={saving || !newName.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {saving ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
                {t("Create")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Soul list */}
      {souls.length === 0 && !creating ? (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
            <Heart size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No souls yet")}
          </p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
            {t(
              "Create your first soul template. Default presets will be seeded automatically on next server restart.",
            )}
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {souls.map((soul) =>
            editing === soul.id ? (
              <div
                key={soul.id}
                className="rounded-xl border border-[var(--ring)] p-5"
              >
                <div className="grid gap-3">
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                      {t("Name")}
                    </label>
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">
                      {t("Content")}
                    </label>
                    <textarea
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      onKeyDown={(e) => handleKeyDown(e, saveSoul)}
                      rows={12}
                      spellCheck={false}
                      className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] leading-6 text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                    />
                  </div>
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={cancelEdit}
                      className="rounded-lg px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    >
                      {t("Cancel")}
                    </button>
                    <button
                      onClick={saveSoul}
                      disabled={saving || !editName.trim()}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
                    >
                      {saving ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Save className="h-3.5 w-3.5" />
                      )}
                      {t("Save")}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div
                key={soul.id}
                className="group flex items-start justify-between rounded-xl border border-[var(--border)] px-5 py-4 transition-colors hover:border-[var(--border)]"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Heart className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
                    <p className="text-[14px] font-medium text-[var(--foreground)]">
                      {soul.name}
                    </p>
                    <span className="text-[11px] text-[var(--muted-foreground)]/60">
                      {soul.id}
                    </span>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)] pl-5.5">
                    {soul.content.replace(/^#.*\n+/g, "").slice(0, 200)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1 ml-4 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => startEdit(soul)}
                    className="inline-flex items-center justify-center rounded-lg border border-[var(--border)]/50 p-1.5 text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    onClick={() => deleteSoul(soul)}
                    className="inline-flex items-center justify-center rounded-lg border border-[var(--border)]/50 p-1.5 text-[var(--muted-foreground)] transition-colors hover:border-red-400/50 hover:text-red-400"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}
