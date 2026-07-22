"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Cpu, Loader2, Plug, Plus, Trash2, X } from "lucide-react";

import { agentGlyph } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  connectSubagent,
  detectSubagents,
  disconnectSubagent,
  listConnectablePartners,
  listSubagentConnections,
  type ConnectablePartner,
  type SubagentBackendInfo,
  type SubagentConnection,
} from "@/lib/subagents-api";

/**
 * Connected agents — live agents the chat composer can select and consult in
 * real time: Claude Code / Codex on the user's machine, or one of their
 * partners. Distinct from the imported-history agents below it: those replay
 * past transcripts, these drive the live agent now. CLI detection is
 * machine-global (is the CLI installed here); partners come from the user's
 * partner list. Consulting a partner opens a fresh session on it — every
 * consult within one DeepTutor chat is archived as one partner session.
 */

const PARTNER_KIND = "partner";

type Lang = { zh: string; en: string };

function backendLabel(kind: string, tr: (l: Lang) => string): string {
  if (kind === "claude_code") return "Claude Code";
  if (kind === "codex") return "Codex";
  if (kind === PARTNER_KIND) return tr({ zh: "伙伴", en: "Partner" });
  return kind;
}

export default function ConnectedAgents() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [backends, setBackends] = useState<SubagentBackendInfo[]>([]);
  const [connections, setConnections] = useState<SubagentConnection[]>([]);
  const [partners, setPartners] = useState<ConnectablePartner[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [busyName, setBusyName] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [detected, conns, parts] = await Promise.all([
        detectSubagents().catch(() => [] as SubagentBackendInfo[]),
        listSubagentConnections().catch(() => [] as SubagentConnection[]),
        listConnectablePartners().catch(() => [] as ConnectablePartner[]),
      ]);
      setBackends(detected);
      setConnections(conns);
      setPartners(parts);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const available = useMemo(
    () => backends.filter((b) => b.available),
    [backends],
  );
  // Something is connectable when a CLI is installed here or a partner exists.
  const canConnect = available.length > 0 || partners.length > 0;
  const partnerName = useCallback(
    (id: string) => partners.find((p) => p.partner_id === id)?.name || id,
    [partners],
  );

  const handleDisconnect = useCallback(
    async (name: string) => {
      if (
        !window.confirm(
          tr({
            zh: `断开「${name}」？这只会移除连接，不影响本机的智能体配置。`,
            en: `Disconnect “${name}”? This only removes the connection; your local agent is untouched.`,
          }),
        )
      )
        return;
      setBusyName(name);
      try {
        await disconnectSubagent(name);
        await load();
      } finally {
        setBusyName(null);
      }
    },
    [load, tr],
  );

  return (
    <section className="space-y-4">
      <SpaceSectionHeader
        icon={Plug}
        title={tr({ zh: "连接的智能体", en: "Connected agents" })}
        description={tr({
          zh: "把本机的 Claude Code / Codex 或你的伙伴接进来，在对话中选中后直接向它提问 —— 它的完整运行过程会实时展示。",
          en: "Bring in the Claude Code / Codex on this machine, or one of your partners — select one in chat to consult it directly, with its full run shown live.",
        })}
        action={
          canConnect ? (
            <button
              type="button"
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] shadow-sm transition-opacity hover:opacity-90"
            >
              <Plus className="h-3.5 w-3.5" />
              {tr({ zh: "连接智能体", en: "Connect agent" })}
            </button>
          ) : null
        }
      />

      {loading ? (
        <div className="flex items-center gap-2 px-1 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {tr({ zh: "检测本机智能体…", en: "Detecting local agents…" })}
        </div>
      ) : !canConnect ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-4 py-5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({
            zh: "未在本机检测到 Claude Code 或 Codex，也还没有任何伙伴。安装并登录其中任一 CLI，或在「伙伴」里新建一个，即可连接。",
            en: "No Claude Code or Codex detected on this machine, and no partners yet. Install and log in to either CLI, or create a partner, to connect one.",
          })}
        </div>
      ) : connections.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-4 py-5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({
            zh: "尚未连接任何智能体。点击「连接智能体」把本机的 Claude Code / Codex 或你的伙伴接进来。",
            en: "No agents connected yet. Click “Connect agent” to bring in your local Claude Code / Codex, or a partner.",
          })}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {connections.map((conn) => {
            const Glyph = agentGlyph(conn.agent_kind);
            // A partner connection wears its own face (the avatar set on the
            // partner page), not the generic heart glyph.
            const partner =
              conn.agent_kind === PARTNER_KIND
                ? partners.find((p) => p.partner_id === conn.partner_id)
                : undefined;
            return (
              <div
                key={conn.name}
                className="group flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3"
              >
                {partner ? (
                  <PartnerAvatar
                    name={partner.name}
                    emoji={partner.emoji}
                    color={partner.color}
                    image={partner.avatar}
                    size={40}
                    className="shrink-0"
                  />
                ) : (
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--border)]/60 bg-[var(--background)] text-[var(--foreground)]">
                    {Glyph ? (
                      <Glyph size={20} />
                    ) : (
                      <Cpu size={18} strokeWidth={1.6} />
                    )}
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-semibold tracking-tight text-[var(--foreground)]">
                    {conn.name}
                  </div>
                  <div className="mt-0.5 truncate text-[11.5px] text-[var(--muted-foreground)]">
                    {backendLabel(conn.agent_kind, tr)}
                    {conn.agent_kind === PARTNER_KIND
                      ? conn.partner_id
                        ? ` · ${partnerName(conn.partner_id)}`
                        : ""
                      : conn.cwd
                        ? ` · ${conn.cwd}`
                        : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void handleDisconnect(conn.name)}
                  disabled={busyName === conn.name}
                  title={tr({ zh: "断开", en: "Disconnect" })}
                  aria-label={tr({ zh: "断开", en: "Disconnect" })}
                  className="rounded-lg border border-[var(--border)]/50 p-2 text-[var(--muted-foreground)] transition-colors hover:border-red-300 hover:text-red-600 disabled:opacity-50 dark:hover:border-red-900 dark:hover:text-red-400"
                >
                  {busyName === conn.name ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {modalOpen && (
        <ConnectModal
          backends={available}
          partners={partners}
          existingNames={connections.map((c) => c.name)}
          tr={tr}
          onClose={() => setModalOpen(false)}
          onConnected={() => {
            setModalOpen(false);
            void load();
          }}
        />
      )}
    </section>
  );
}

function ConnectModal({
  backends,
  partners,
  existingNames,
  tr,
  onClose,
  onConnected,
}: {
  backends: SubagentBackendInfo[];
  partners: ConnectablePartner[];
  existingNames: string[];
  tr: (l: Lang) => string;
  onClose: () => void;
  onConnected: () => void;
}) {
  // The agent-type choices: each detected CLI, plus "Partner" when any exist.
  const options = useMemo(
    () => [
      ...backends.map((b) => ({ kind: b.kind, label: b.display_name })),
      ...(partners.length
        ? [{ kind: PARTNER_KIND, label: tr({ zh: "伙伴", en: "Partner" }) }]
        : []),
    ],
    [backends, partners, tr],
  );

  const [kind, setKind] = useState(options[0]?.kind ?? "");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [cwd, setCwd] = useState("");
  const [partnerId, setPartnerId] = useState(partners[0]?.partner_id ?? "");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isPartner = kind === PARTNER_KIND;

  // While the user hasn't renamed the connection, mirror the chosen partner's
  // name so the connection reads as that partner by default.
  useEffect(() => {
    if (!isPartner || nameTouched) return;
    const picked = partners.find((p) => p.partner_id === partnerId);
    setName(picked?.name ?? "");
  }, [isPartner, nameTouched, partnerId, partners]);

  const submit = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(tr({ zh: "请填写名称。", en: "Please enter a name." }));
      return;
    }
    if (existingNames.includes(trimmed)) {
      setError(
        tr({
          zh: "已存在同名连接。",
          en: "A connection with this name already exists.",
        }),
      );
      return;
    }
    if (isPartner && !partnerId) {
      setError(tr({ zh: "请选择一个伙伴。", en: "Please pick a partner." }));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await connectSubagent(
        isPartner
          ? { name: trimmed, agent_kind: PARTNER_KIND, partner_id: partnerId }
          : { name: trimmed, agent_kind: kind, cwd: cwd.trim() },
      );
      onConnected();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [name, kind, cwd, isPartner, partnerId, existingNames, onConnected, tr]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
            {tr({ zh: "连接智能体", en: "Connect an agent" })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
            aria-label={tr({ zh: "关闭", en: "Close" })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3.5">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
              {tr({ zh: "智能体", en: "Agent" })}
            </label>
            <div className="flex gap-2">
              {options.map((opt) => {
                const Glyph = agentGlyph(opt.kind);
                return (
                  <button
                    key={opt.kind}
                    type="button"
                    onClick={() => setKind(opt.kind)}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-[12.5px] font-medium transition-colors ${
                      kind === opt.kind
                        ? "border-[var(--primary)] bg-[var(--primary)]/[0.07] text-[var(--foreground)]"
                        : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {Glyph ? <Glyph size={15} /> : null}
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {isPartner && (
            <div>
              <label className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
                {tr({ zh: "伙伴", en: "Partner" })}
              </label>
              <select
                value={partnerId}
                onChange={(e) => setPartnerId(e.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              >
                {partners.map((p) => (
                  <option key={p.partner_id} value={p.partner_id}>
                    {p.emoji ? `${p.emoji} ` : ""}
                    {p.name}
                    {p.description ? ` — ${p.description}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
              {tr({ zh: "名称", en: "Name" })}
            </label>
            <input
              autoFocus
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameTouched(true);
              }}
              placeholder={tr({
                zh: "例如：我的代码助手",
                en: "e.g. My coding agent",
              })}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            />
          </div>

          {!isPartner && (
            <div>
              <label className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
                {tr({
                  zh: "工作目录（可选）",
                  en: "Working directory (optional)",
                })}
              </label>
              <input
                value={cwd}
                onChange={(e) => setCwd(e.target.value)}
                placeholder={tr({
                  zh: "例如：/Users/you/project —— 智能体将在此目录运行",
                  en: "e.g. /Users/you/project — the agent runs here",
                })}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </div>
          )}

          {isPartner && (
            <p className="text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
              {tr({
                zh: "在对话中咨询该伙伴时，会像在伙伴页开启一个新 session；同一对话里的多次咨询都会归档为同一个 session。",
                en: "Consulting this partner in chat opens a session on it, just like the partner page; every consult within one chat is archived as the same session.",
              })}
            </p>
          )}

          {error && (
            <p className="text-[12px] text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            {tr({ zh: "取消", en: "Cancel" })}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--background)] shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plug className="h-3.5 w-3.5" />
            )}
            {tr({ zh: "连接", en: "Connect" })}
          </button>
        </div>
      </div>
    </div>
  );
}
