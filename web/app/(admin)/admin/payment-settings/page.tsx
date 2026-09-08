"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchGatewayConfig,
  saveGatewayConfig,
  type GatewayConfigPayload,
} from "@/lib/payment-admin-api";
import {
  ArrowLeft,
  CreditCard,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

type SaveState = "idle" | "saving" | "saved" | "error";

interface TextFieldDef {
  key: string;
  label: string;
  placeholder: string;
  secret?: boolean;
  help?: string;
}

const WECHAT_FIELDS: TextFieldDef[] = [
  { key: "appid", label: "AppID", placeholder: "wx1234567890abcdef" },
  { key: "mchid", label: "商户号 (Mch ID)", placeholder: "1900000109" },
  { key: "merchant_serial_no", label: "API 证书序列号", placeholder: "1234567890ABCDEF" },
  {
    key: "merchant_private_key_path",
    label: "商户私钥路径",
    placeholder: "/data/certs/apiclient_key.pem",
    secret: true,
    help: "APIv3 商户私钥 PEM 文件路径（部署内路径）。",
  },
  {
    key: "platform_cert_pem",
    label: "平台证书 PEM",
    placeholder: "-----BEGIN CERTIFICATE----- …",
    secret: true,
    help: "微信支付平台证书公钥（用于回调验签）。",
  },
  {
    key: "api_v3_key",
    label: "APIv3 密钥",
    placeholder: "32 位密钥",
    secret: true,
    help: "用于解密回调报文 resource 字段。",
  },
];

const EPAY_FIELDS: TextFieldDef[] = [
  { key: "gateway_url", label: "网关地址", placeholder: "https://pay.example.com" },
  { key: "pid", label: "商户 PID", placeholder: "1001" },
  { key: "merchant_key", label: "商户密钥 (Key)", placeholder: "32 位密钥", secret: true },
];

const CDK_FIELDS: TextFieldDef[] = [
  { key: "enabled", label: "启用卡密通道", placeholder: "", help: "开启后学员可在购买页使用卡密兑换。" },
];

interface ChannelDraft {
  [key: string]: string | boolean;
}

function emptyDraft(config: GatewayConfigPayload): Record<string, ChannelDraft> {
  const out: Record<string, ChannelDraft> = {};
  for (const name of ["wechat", "epay", "cdk"] as const) {
    const cfg = (config[name] ?? {}) as Record<string, unknown>;
    const draft: ChannelDraft = {};
    for (const [key, value] of Object.entries(cfg)) {
      if (typeof value === "boolean") draft[key] = value;
      else if (typeof value === "number") draft[key] = String(value);
      else if (typeof value === "string") draft[key] = value;
      else draft[key] = "";
    }
    // Ensure the toggle always has a concrete value.
    if (typeof draft.enabled !== "boolean") draft.enabled = Boolean(cfg.enabled);
    out[name] = draft;
  }
  return out;
}

function ChannelCard({
  title,
  icon,
  enabled,
  onToggleEnabled,
  fields,
  draft,
  onFieldChange,
}: {
  title: string;
  icon: React.ReactNode;
  enabled: boolean;
  onToggleEnabled: () => void;
  fields: TextFieldDef[];
  draft: ChannelDraft;
  onFieldChange: (key: string, value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--muted)]/50 text-[var(--muted-foreground)]">
            {icon}
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[var(--foreground)]">
              {title}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)]">
              {enabled ? t("Enabled") : t("Disabled")}
            </p>
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={t("Enable {{channel}}", { channel: title })}
          onClick={onToggleEnabled}
          className={`relative h-6 w-11 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
            enabled ? "bg-[var(--primary)]" : "bg-[var(--muted)]/70"
          }`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
              enabled ? "left-[22px]" : "left-0.5"
            }`}
          />
        </button>
      </div>

      <div className="space-y-3">
        {fields.map((field) => {
          if (field.key === "enabled") {
            return (
              <p
                key={field.key}
                className="text-xs leading-relaxed text-[var(--muted-foreground)]"
              >
                {t(field.help ?? "")}
              </p>
            );
          }
          return (
            <label key={field.key} className="block text-xs text-[var(--muted-foreground)]">
              <span className="mb-1 block">{t(field.label)}</span>
              <input
                type={field.secret ? "password" : "text"}
                value={typeof draft[field.key] === "string" ? (draft[field.key] as string) : ""}
                onChange={(e) => onFieldChange(field.key, e.target.value)}
                autoComplete="off"
                placeholder={field.placeholder}
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
              {field.help && (
                <span className="mt-1 block text-[11px] leading-relaxed text-[var(--muted-foreground)]/70">
                  {t(field.help)}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
}

export default function PaymentSettingsPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [config, setConfig] = useState<GatewayConfigPayload>({
    wechat: {},
    epay: {},
    cdk: {},
  });
  const [drafts, setDrafts] = useState<Record<string, ChannelDraft>>({
    wechat: {},
    epay: {},
    cdk: {},
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await fetchGatewayConfig();
      setConfig(next);
      setDrafts(emptyDraft(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load gateway configuration"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }
      void load();
    });
  }, [router, load]);

  function setChannelDraft(name: "wechat" | "epay" | "cdk", next: ChannelDraft) {
    setDrafts((current) => ({ ...current, [name]: next }));
  }

  function toggleEnabled(name: "wechat" | "epay" | "cdk") {
    const draft = drafts[name];
    setChannelDraft(name, { ...draft, enabled: !draft.enabled });
  }

  function handleFieldChange(name: "wechat" | "epay" | "cdk") {
    return (key: string, value: string) => {
      const draft = drafts[name];
      const next: ChannelDraft = { ...draft };
      // Preserve the enabled toggle even if a field is being edited.
      if (typeof draft.enabled === "boolean") next.enabled = draft.enabled;
      next[key] = value;
      setChannelDraft(name, next);
    };
  }

  async function handleSave() {
    if (saveState === "saving") return;
    setSaveState("saving");
    setMessage("");
    try {
      const payload: GatewayConfigPayload = {
        wechat: { ...drafts.wechat, enabled: Boolean(drafts.wechat.enabled) },
        epay: { ...drafts.epay, enabled: Boolean(drafts.epay.enabled) },
        cdk: { ...drafts.cdk, enabled: Boolean(drafts.cdk.enabled) },
      };
      const saved = await saveGatewayConfig(payload);
      setConfig(saved);
      setDrafts(emptyDraft(saved));
      setSaveState("saved");
      setMessage(t("Payment settings saved."));
    } catch (e) {
      setSaveState("error");
      setMessage(e instanceof Error ? e.message : t("Failed to save payment settings"));
    }
  }

  const saving = saveState === "saving";

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="mb-8">
          <Link
            href="/admin"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back to Admin")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <CreditCard size={18} className="text-[var(--muted-foreground)]" />
                <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                  {t("Payment Settings")}
                </h1>
              </div>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Configure WeChat Pay, the EPay gateway and the CDK channel.")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                onClick={load}
                disabled={loading || saving}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--muted-foreground)]
                           hover:text-[var(--foreground)] hover:bg-[var(--card)]
                           disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
                {t("Refresh")}
              </button>
              <button
                onClick={handleSave}
                disabled={loading || saving}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium
                           bg-[var(--foreground)] text-[var(--background)] hover:opacity-90
                           disabled:opacity-40 transition-opacity"
              >
                {saving ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Save size={14} />
                )}
                {saving ? t("Saving…") : t("Save")}
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {message && saveState !== "error" && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-600 dark:text-green-400">
            <ShieldCheck size={14} />
            {message}
          </div>
        )}

        {loading ? (
          <div className="space-y-4" aria-hidden>
            {[0, 1, 2].map((row) => (
              <div
                key={row}
                className="flex animate-pulse items-start gap-3 rounded-2xl border border-[var(--border)] p-5"
              >
                <div className="h-8 w-8 rounded-lg bg-[var(--muted)]/60" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                  <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <ChannelCard
              title={t("WeChat Pay")}
              icon={<span className="text-base font-semibold">微</span>}
              enabled={Boolean(drafts.wechat.enabled)}
              onToggleEnabled={() => toggleEnabled("wechat")}
              fields={WECHAT_FIELDS}
              draft={drafts.wechat}
              onFieldChange={handleFieldChange("wechat")}
            />
            <ChannelCard
              title={t("EPay Gateway")}
              icon={<span className="text-base font-semibold">易</span>}
              enabled={Boolean(drafts.epay.enabled)}
              onToggleEnabled={() => toggleEnabled("epay")}
              fields={EPAY_FIELDS}
              draft={drafts.epay}
              onFieldChange={handleFieldChange("epay")}
            />
            <ChannelCard
              title={t("CDK Card Keys")}
              icon={<span className="text-base font-semibold">卡</span>}
              enabled={Boolean(drafts.cdk.enabled)}
              onToggleEnabled={() => toggleEnabled("cdk")}
              fields={CDK_FIELDS}
              draft={drafts.cdk}
              onFieldChange={handleFieldChange("cdk")}
            />
          </div>
        )}

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · Payment Settings")}
        </p>
      </div>
    </div>
  );
}
