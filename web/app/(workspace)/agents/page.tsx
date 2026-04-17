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
import { apiUrl } from "@/lib/api";

const MarkdownRenderer = dynamic(() => import("@/components/common/MarkdownRenderer"), {
  ssr: false,
});

/* ── Types ──────────────────────────────────────────────── */

interface BotInfo {
  bot_id: string;
  name: string;
  description: string;
  persona: string;
  /** Compact list from `GET /tutorbot`; full dict from `GET /tutorbot/{id}` */
  channels: string[] | Record<string, unknown>;
  model: string | null;
  running: boolean;
  started_at: string | null;
}

interface SoulTemplate {
  id: string;
  name: string;
  content: string;
}

type Tab = "bots" | "profiles" | "channels" | "souls";

const BOT_FILES = ["SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "HEARTBEAT.md"] as const;
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

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const loadBots = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/v1/tutorbot"));
      setBots(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSouls = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/tutorbot/souls"));
      if (res.ok) setSouls(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void loadBots(); void loadSouls(); }, [loadBots, loadSouls]);

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("TutorBot Agents")}
          </h1>
          {toast ? (
            <p className="mt-1 text-[13px] text-[var(--primary)] animate-fade-in">{toast}</p>
          ) : (
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Manage your in-process TutorBot instances")}
            </p>
          )}
        </div>

        {/* Tabs */}
        <div className="mb-6 flex items-center gap-1 border-b border-[var(--border)]/50 pb-3">
          {([
            { key: "bots" as Tab, label: t("Bots"), icon: Bot },
            { key: "profiles" as Tab, label: t("Profiles"), icon: FileText },
            { key: "channels" as Tab, label: t("Channels"), icon: Settings2 },
            { key: "souls" as Tab, label: t("Souls"), icon: Heart },
          ]).map((tab) => {
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
            onReload={loadBots}
            onToast={setToast}
            router={router}
          />
        ) : activeTab === "profiles" ? (
          <ProfilesTab bots={bots} loading={loading} onToast={setToast} />
        ) : activeTab === "channels" ? (
          <ChannelsTab bots={bots} loading={loading} onToast={setToast} onReload={loadBots} />
        ) : (
          <SoulsTab souls={souls} onReload={loadSouls} onToast={setToast} />
        )}
      </div>
    </div>
  );
}

/* ── Channels tab (Telegram + globals) ─────────────────── */

const DEFAULT_TELEGRAM = {
  enabled: false,
  token: "",
  allow_from: [] as string[],
  proxy: "" as string,
  reply_to_message: false,
  group_policy: "mention" as "open" | "mention",
};

function normalizeChannelsDict(raw: Record<string, unknown> | undefined): Record<string, unknown> {
  const r = { ...(raw ?? {}) };
  const tg = (r.telegram as Record<string, unknown> | undefined) ?? {};
  const allowRaw = tg.allow_from;
  const allow_from = Array.isArray(allowRaw) ? allowRaw.map(String) : [];
  return {
    ...r,
    send_progress: r.send_progress !== false,
    send_tool_hints: !!r.send_tool_hints,
    telegram: {
      ...DEFAULT_TELEGRAM,
      ...tg,
      allow_from,
      group_policy: tg.group_policy === "open" ? "open" : "mention",
    },
  };
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
  const [channels, setChannels] = useState<Record<string, unknown>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (bots.length > 0 && !selectedBot) setSelectedBot(bots[0].bot_id);
  }, [bots, selectedBot]);

  useEffect(() => {
    setShowToken(false);
  }, [selectedBot]);

  const loadDetail = useCallback(async (bid: string) => {
    if (!bid) return;
    setLoadingDetail(true);
    try {
      const res = await fetch(apiUrl(`/api/v1/tutorbot/${bid}`));
      if (!res.ok) return;
      const data = await res.json();
      setChannels(normalizeChannelsDict(data.channels as Record<string, unknown> | undefined));
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selectedBot) void loadDetail(selectedBot);
  }, [selectedBot, loadDetail]);

  const tg = (channels.telegram as typeof DEFAULT_TELEGRAM) ?? DEFAULT_TELEGRAM;

  const setTg = (patch: Partial<typeof DEFAULT_TELEGRAM>) => {
    setChannels((prev) => ({
      ...prev,
      telegram: { ...DEFAULT_TELEGRAM, ...(prev.telegram as object), ...patch },
    }));
  };

  const buildPayload = (): Record<string, unknown> => {
    const allow_from = Array.isArray(tg.allow_from)
      ? tg.allow_from.map(String)
      : [];
    const proxyVal = typeof tg.proxy === "string" && tg.proxy.trim() ? tg.proxy.trim() : null;
    const next: Record<string, unknown> = { ...channels };
    next.send_progress = !!channels.send_progress;
    next.send_tool_hints = !!channels.send_tool_hints;
    next.telegram = {
      enabled: !!tg.enabled,
      token: String(tg.token ?? ""),
      allow_from,
      proxy: proxyVal,
      reply_to_message: !!tg.reply_to_message,
      group_policy: tg.group_policy === "open" ? "open" : "mention",
    };
    return next;
  };

  const save = async () => {
    if (!selectedBot) return;
    setSaving(true);
    try {
      const res = await fetch(apiUrl(`/api/v1/tutorbot/${selectedBot}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channels: buildPayload() }),
      });
      if (res.ok) {
        onToast(t("Channels saved"));
        await onReload();
        await loadDetail(selectedBot);
      } else {
        const err = await res.json().catch(() => ({}));
        onToast((err as { detail?: string }).detail ?? t("Save failed"));
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
        <p className="text-[14px] font-medium text-[var(--foreground)]">{t("No bots to configure")}</p>
        <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
          {t("Create a bot first in the Bots tab.")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-[12px] font-medium text-[var(--muted-foreground)] shrink-0">{t("Bot")}</label>
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
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          {t("Save")}
        </button>
      </div>

      {loadingDetail ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
            <h3 className="text-[13px] font-medium text-[var(--foreground)]">{t("Delivery")}</h3>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!channels.send_progress}
                onChange={(e) => setChannels((c) => ({ ...c, send_progress: e.target.checked }))}
              />
              {t("Stream progress text to channels")}
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!channels.send_tool_hints}
                onChange={(e) => setChannels((c) => ({ ...c, send_tool_hints: e.target.checked }))}
              />
              {t("Stream tool hints to channels")}
            </label>
          </div>

          <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
            <h3 className="text-[13px] font-medium text-[var(--foreground)]">{t("Telegram")}</h3>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!tg.enabled}
                onChange={(e) => setTg({ enabled: e.target.checked })}
              />
              {t("Enabled")}
            </label>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Bot token")}</label>
              <div className="relative">
                <input
                  type={showToken ? "text" : "password"}
                  autoComplete="off"
                  value={tg.token}
                  onChange={(e) => setTg({ token: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-transparent py-2 pl-3 pr-10 font-mono text-[13px] outline-none focus:border-[var(--ring)]"
                />
                <button
                  type="button"
                  onClick={() => setShowToken((v) => !v)}
                  className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  aria-label={showToken ? t("Hide token") : t("Show token")}
                  title={showToken ? t("Hide token") : t("Show token")}
                >
                  {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Allowed user IDs (one per line)")}</label>
              <textarea
                value={tg.allow_from.join("\n")}
                onChange={(e) =>
                  setTg({
                    allow_from: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                  })
                }
                rows={4}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none focus:border-[var(--ring)]"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Proxy URL")} <span className="font-normal opacity-60">{t("(optional)")}</span></label>
              <input
                value={tg.proxy ?? ""}
                onChange={(e) => setTg({ proxy: e.target.value })}
                placeholder="http://127.0.0.1:7890"
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-[var(--ring)]"
              />
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={!!tg.reply_to_message}
                onChange={(e) => setTg({ reply_to_message: e.target.checked })}
              />
              {t("Reply to the user message (vs new message)")}
            </label>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Group policy")}</label>
              <select
                value={tg.group_policy}
                onChange={(e) => setTg({ group_policy: e.target.value as "open" | "mention" })}
                className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
              >
                <option value="mention">{t("Mention only")}</option>
                <option value="open">{t("Open (all messages)")}</option>
              </select>
            </div>
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
  onReload,
  onToast,
  router,
}: {
  bots: BotInfo[];
  souls: SoulTemplate[];
  loading: boolean;
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
  const [formModel, setFormModel] = useState("");

  const resetForm = () => {
    setFormName(""); setFormDesc(""); setFormSoulId("_custom");
    setFormSoul(""); setFormModel("");
  };

  const botId = useMemo(() => {
    const slug = formName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return slug || "";
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
      const res = await fetch(apiUrl("/api/v1/tutorbot"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_id: botId,
          name: formName.trim(),
          description: formDesc.trim(),
          persona: formSoul.trim(),
          model: formModel.trim() || undefined,
        }),
      });
      if (res.ok) {
        onToast(`${formName.trim()} created`);
        setShowCreate(false);
        resetForm();
        await onReload();
      }
    } finally {
      setCreating(false);
    }
  }, [botId, formName, formDesc, formSoul, formModel, onReload, onToast]);

  const startBot = useCallback(async (bid: string) => {
    const res = await fetch(apiUrl("/api/v1/tutorbot"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_id: bid }),
    });
    if (res.ok) { onToast(`${bid} started`); await onReload(); }
  }, [onReload, onToast]);

  const stopBot = useCallback(async (bid: string) => {
    const res = await fetch(apiUrl(`/api/v1/tutorbot/${bid}`), { method: "DELETE" });
    if (res.ok) { onToast(`${bid} stopped`); await onReload(); }
  }, [onReload, onToast]);

  const destroyBot = useCallback(async (bid: string, name: string) => {
    if (!window.confirm(t("Permanently delete \"{{name}}\" ({{id}})? This cannot be undone.", { name, id: bid }))) return;
    const res = await fetch(apiUrl(`/api/v1/tutorbot/${bid}/destroy`), { method: "DELETE" });
    if (res.ok) { onToast(`${name} deleted`); await onReload(); }
  }, [onReload, onToast, t]);

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
            <h2 className="text-[15px] font-medium text-[var(--foreground)]">{t("Create TutorBot")}</h2>
            <button onClick={() => { setShowCreate(false); resetForm(); }} className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Name")}</label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder={t("e.g. Math Tutor")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              {botId && (
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">ID: {botId}</p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Description")} <span className="font-normal opacity-60">{t("(optional)")}</span></label>
              <input
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                placeholder={t("A brief description of what this bot does")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Soul")}</label>
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
                onChange={(e) => { setFormSoul(e.target.value); setFormSoulId("_custom"); }}
                placeholder={t("Define the bot's personality, values, and communication style in markdown...")}
                rows={8}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] leading-6 text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/60">
                {t("Pick a soul from the library above, or write your own. Manage the library in the Souls tab.")}
              </p>
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Model")} <span className="font-normal opacity-60">{t("(optional)")}</span></label>
              <input
                value={formModel}
                onChange={(e) => setFormModel(e.target.value)}
                placeholder={t("Uses default model if empty")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
            </div>
            <div className="flex justify-end">
              <button
                onClick={createBot}
                disabled={creating || !botId}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
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
          <p className="text-[14px] font-medium text-[var(--foreground)]">{t("No TutorBots yet")}</p>
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
                <div className={`h-2 w-2 shrink-0 rounded-full ${bot.running ? "bg-emerald-500" : "bg-[var(--muted-foreground)]/30"}`} />
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-[var(--foreground)] truncate">{bot.name}</p>
                  <div className="mt-0.5 flex items-center gap-3 text-[12px] text-[var(--muted-foreground)]">
                    {bot.description ? (
                      <span className="truncate max-w-[300px]">{bot.description}</span>
                    ) : (
                      <span>{bot.bot_id}</span>
                    )}
                    {bot.model && <span>· {bot.model}</span>}
                    {bot.started_at && (
                      <span>· {t("started {{time}}", { time: new Date(bot.started_at).toLocaleString() })}</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
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
  loading,
  onToast,
}: {
  bots: BotInfo[];
  loading: boolean;
  onToast: (msg: string) => void;
}) {
  const { t } = useTranslation();
  const [selectedBot, setSelectedBot] = useState<string>("");
  const [activeFile, setActiveFile] = useState<BotFile>("SOUL.md");
  const [files, setFiles] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState("");
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeView, setActiveView] = useState<"edit" | "preview">("edit");

  const hasChanges = editor !== (files[activeFile] ?? "");

  useEffect(() => {
    if (bots.length > 0 && !selectedBot) {
      setSelectedBot(bots[0].bot_id);
    }
  }, [bots, selectedBot]);

  const loadFiles = useCallback(async (bid: string) => {
    if (!bid) return;
    setLoadingFiles(true);
    try {
      const res = await fetch(apiUrl(`/api/v1/tutorbot/${bid}/files`));
      const data: Record<string, string> = await res.json();
      setFiles(data);
      setEditor(data[activeFile] ?? "");
    } finally {
      setLoadingFiles(false);
    }
  }, [activeFile]);

  useEffect(() => {
    if (selectedBot) void loadFiles(selectedBot);
  }, [selectedBot, loadFiles]);

  useEffect(() => {
    setEditor(files[activeFile] ?? "");
    setActiveView("edit");
  }, [activeFile, files]);

  const saveFile = useCallback(async () => {
    if (!selectedBot) return;
    setSaving(true);
    try {
      const res = await fetch(apiUrl(`/api/v1/tutorbot/${selectedBot}/files/${activeFile}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: editor }),
      });
      if (res.ok) {
        setFiles((prev) => ({ ...prev, [activeFile]: editor }));
        onToast(`${activeFile} saved`);
      }
    } finally {
      setSaving(false);
    }
  }, [selectedBot, activeFile, editor, onToast]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        void saveFile();
      }
    },
    [saveFile],
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
        <p className="text-[14px] font-medium text-[var(--foreground)]">{t("No bots to configure")}</p>
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
        <label className="text-[12px] font-medium text-[var(--muted-foreground)] shrink-0">{t("Bot")}</label>
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
        <div className="flex items-center gap-1">
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
        </div>
        <button
          onClick={saveFile}
          disabled={saving || !hasChanges}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
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
            onChange={(e) => setEditor(e.target.value)}
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
          <MarkdownRenderer content={editor} variant="prose" className="text-[14px] leading-relaxed" />
        </div>
      ) : (
        <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
          <p className="text-[14px] font-medium text-[var(--foreground)]">{t("{{file}} is empty", { file: activeFile })}</p>
          <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
            {t("Switch to Edit to add content.")}
          </p>
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
      const res = await fetch(apiUrl(`/api/v1/tutorbot/souls/${editing}`), {
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
    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!id) return;
    setSaving(true);
    try {
      const res = await fetch(apiUrl("/api/v1/tutorbot/souls"), {
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

  const deleteSoul = useCallback(async (soul: SoulTemplate) => {
    if (!window.confirm(t("Delete soul \"{{name}}\"?", { name: soul.name }))) return;
    const res = await fetch(apiUrl(`/api/v1/tutorbot/souls/${soul.id}`), { method: "DELETE" });
    if (res.ok) {
      if (editing === soul.id) cancelEdit();
      onToast(`"${soul.name}" deleted`);
      await onReload();
    }
  }, [editing, onReload, onToast, t]);

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
            <h2 className="text-[15px] font-medium text-[var(--foreground)]">{t("New Soul")}</h2>
            <button onClick={() => setCreating(false)} className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Name")}</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t("e.g. Creative Writer")}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40"
              />
              {newName.trim() && (
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  ID: {newName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Content")}</label>
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
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
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
          <p className="text-[14px] font-medium text-[var(--foreground)]">{t("No souls yet")}</p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
            {t("Create your first soul template. Default presets will be seeded automatically on next server restart.")}
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {souls.map((soul) =>
            editing === soul.id ? (
              <div key={soul.id} className="rounded-xl border border-[var(--ring)] p-5">
                <div className="grid gap-3">
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Name")}</label>
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-[var(--muted-foreground)]">{t("Content")}</label>
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
                      {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
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
                    <p className="text-[14px] font-medium text-[var(--foreground)]">{soul.name}</p>
                    <span className="text-[11px] text-[var(--muted-foreground)]/60">{soul.id}</span>
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
