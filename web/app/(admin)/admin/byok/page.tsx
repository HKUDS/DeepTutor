"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, KeyRound, Loader2, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchAdminByokPolicy,
  saveAdminByokPolicy,
  type AdminByokPolicy,
} from "@/features/byok/admin-api";
import { parseEndpointAllowlist } from "@/features/byok/helpers";

const SERVICES = ["llm", "embedding", "mineru"] as const;
type Service = (typeof SERVICES)[number];

const LABELS: Record<Service, string> = {
  llm: "LLM",
  embedding: "Embedding",
  mineru: "MinerU",
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function AdminByokPage() {
  const router = useRouter();
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const copy = zh
    ? {
        authUnavailable: "无法验证当前登录状态，请检查服务连接后重试。",
        authDisabled: "身份验证未启用时，BYOK 会保持故障关闭状态。",
        back: "返回用户管理",
        cloud: "云端",
        customEndpoint: "自定义端点",
        endpointAllowlist: "端点白名单",
        endpointHelp:
          "每行一个精确 HTTPS URL。私有、回环和元数据地址仍会被拦截。",
        globalByok: "全局 BYOK",
        loadFailed: "无法读取 BYOK 策略",
        loading: "正在加载 BYOK 策略…",
        masterKeyMissing: "未配置主密钥",
        policyDescription:
          "控制全局 BYOK、provider 白名单和安全上限；不会显示任何用户密钥。",
        policyTitle: "BYOK 策略",
        providersPlaceholder: "允许的 provider，以逗号分隔",
        ready: "已就绪",
        retry: "重试",
        save: "保存",
        saveFailed: "保存失败",
        saved: "已保存",
        saving: "正在保存…",
        safetyHelp: "这些上限同样适用于 BYOK；这里的 0 不表示无限制。",
        safetyLimits: "安全上限",
        serviceEnabled: "启用",
        serviceHelp:
          "用户授权也必须允许 BYOK。平台配额和沙箱限制仍独立生效。",
        servicePolicy: "服务策略",
        maxMineruPages: "每个 MinerU 文件最大页数",
        maxTokens: "每次请求最大 LLM token 数",
        requestsPerMinute: "每分钟 BYOK 请求数",
        vault: "密钥库",
      }
    : {
        authUnavailable:
          "Unable to verify the current session. Check the service connection and try again.",
        authDisabled: "BYOK remains fail-closed while authentication is disabled.",
        back: "Back to users",
        cloud: "Cloud",
        customEndpoint: "Custom endpoint",
        endpointAllowlist: "Endpoint allowlist",
        endpointHelp:
          "One exact HTTPS URL per line. Private, loopback, and metadata addresses remain blocked.",
        globalByok: "Global BYOK",
        loadFailed: "Unable to load the BYOK policy",
        loading: "Loading BYOK policy…",
        masterKeyMissing: "master key missing",
        policyDescription:
          "Control global BYOK, provider allowlists, and safety limits. User secrets are never shown.",
        policyTitle: "BYOK policy",
        providersPlaceholder: "Allowed providers, comma separated",
        ready: "ready",
        retry: "Retry",
        save: "Save",
        saveFailed: "Unable to save the BYOK policy",
        saved: "Saved",
        saving: "Saving…",
        safetyHelp:
          "These limits apply to BYOK too; zero is not treated as unlimited here.",
        safetyLimits: "Safety limits",
        serviceEnabled: "Enabled",
        serviceHelp:
          "The user grant must also allow BYOK. Platform quotas and sandbox limits remain separate.",
        servicePolicy: "Service policy",
        maxMineruPages: "Max MinerU pages/file",
        maxTokens: "Max LLM tokens/request",
        requestsPerMinute: "BYOK requests/min",
        vault: "Vault",
      };
  const [policy, setPolicy] = useState<AdminByokPolicy | null>(null);
  const [endpointAllowlistText, setEndpointAllowlistText] = useState("");
  const [authEnabled, setAuthEnabled] = useState(false);
  const [vaultAvailable, setVaultAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadPolicy() {
      setLoading(true);
      setMessage("");
      try {
        const auth = await fetchAuthStatus();
        if (cancelled) return;
        if (!auth) {
          setMessage(copy.authUnavailable);
          return;
        }
        if (!auth.authenticated) {
          setMessage(zh ? "正在跳转到登录页…" : "Redirecting to login…");
          router.replace("/login");
          return;
        }
        if (auth.role !== "admin") {
          router.replace("/");
          return;
        }

        const data = await fetchAdminByokPolicy();
        if (cancelled) return;
        setPolicy(data.policy);
        setEndpointAllowlistText(data.policy.endpoint_allowlist.join("\n"));
        setAuthEnabled(data.auth_enabled);
        setVaultAvailable(data.vault_available);
      } catch (error) {
        if (!cancelled) setMessage(errorMessage(error, copy.loadFailed));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadPolicy();
    return () => {
      cancelled = true;
    };
  }, [copy.authUnavailable, copy.loadFailed, loadAttempt, router, zh]);

  function updateService(
    service: Service,
    patch: Partial<AdminByokPolicy["services"][Service]>,
  ) {
    setPolicy((current) =>
      current
        ? {
            ...current,
            services: {
              ...current.services,
              [service]: { ...current.services[service], ...patch },
            },
          }
        : current,
    );
  }

  async function save() {
    if (!policy) return;
    setSaving(true);
    setMessage("");
    try {
      // Read the draft at submit time so keyboard-only users can press Save
      // directly without first blurring the textarea.
      const saved = await saveAdminByokPolicy({
        ...policy,
        endpoint_allowlist: parseEndpointAllowlist(endpointAllowlistText),
      });
      setPolicy(saved);
      setEndpointAllowlistText(saved.endpoint_allowlist.join("\n"));
      setMessage(copy.saved);
    } catch (error) {
      setMessage(errorMessage(error, copy.saveFailed));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="animate-spin" size={18} />
        {copy.loading}
      </div>
    );
  }

  if (!policy) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--background)] px-4 py-10">
        <div className="max-w-md rounded-2xl border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-700 dark:text-red-200">
          <p>{message || copy.loadFailed}</p>
          <button
            type="button"
            onClick={() => setLoadAttempt((current) => current + 1)}
            className="mt-3 rounded-lg border border-current px-3 py-1.5 text-xs font-medium"
          >
            {copy.retry}
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[var(--background)] px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <Link
          href="/admin/users"
          className="mb-5 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={16} /> {copy.back}
        </Link>
        <div className="mb-6 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-xl bg-fuchsia-500/10 p-2.5 text-fuchsia-600 dark:text-fuchsia-400">
              <KeyRound size={20} />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-[var(--foreground)]">
                {copy.policyTitle}
              </h1>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {copy.policyDescription}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs font-medium text-[var(--background)] disabled:opacity-50"
          >
            <Save size={14} /> {saving ? copy.saving : copy.save}
          </button>
        </div>

        {!authEnabled ? (
          <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">
            {copy.authDisabled}
          </div>
        ) : null}
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <div
            className={`rounded-xl border px-4 py-3 text-sm ${
              vaultAvailable
                ? "border-emerald-500/30 bg-emerald-500/10"
                : "border-amber-500/30 bg-amber-500/10"
            }`}
          >
            <span className="font-medium">{copy.vault}</span>
            <span className="ml-2 text-[var(--muted-foreground)]">
              {vaultAvailable ? copy.ready : copy.masterKeyMissing}
            </span>
          </div>
          <label className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--foreground)]">
            <span>{copy.globalByok}</span>
            <input
              type="checkbox"
              checked={policy.enabled}
              onChange={(event) =>
                setPolicy({ ...policy, enabled: event.target.checked })
              }
            />
          </label>
        </div>

        <section className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">
            {copy.servicePolicy}
          </h2>
          <p className="mb-4 text-xs text-[var(--muted-foreground)]">
            {copy.serviceHelp}
          </p>
          <div className="space-y-3">
            {SERVICES.map((service) => {
              const item = policy.services[service];
              return (
                <div
                  key={service}
                  className="rounded-xl border border-[var(--border)]/70 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="text-sm font-medium text-[var(--foreground)]">
                      {LABELS[service]}
                    </span>
                    <div className="flex items-center gap-3 text-xs text-[var(--muted-foreground)]">
                      <label className="inline-flex items-center gap-1.5">
                        <input
                          type="checkbox"
                          checked={item.enabled}
                          onChange={(event) =>
                            updateService(service, {
                              enabled: event.target.checked,
                            })
                          }
                        />
                        {copy.serviceEnabled}
                      </label>
                      {service === "mineru" ? (
                        <label className="inline-flex items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={item.allow_cloud !== false}
                            onChange={(event) =>
                              updateService(service, {
                                allow_cloud: event.target.checked,
                              })
                            }
                          />
                          {copy.cloud}
                        </label>
                      ) : (
                        <label className="inline-flex items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={item.allow_custom_endpoints === true}
                            onChange={(event) =>
                              updateService(service, {
                                allow_custom_endpoints: event.target.checked,
                              })
                            }
                          />
                          {copy.customEndpoint}
                        </label>
                      )}
                    </div>
                  </div>
                  <input
                    value={item.allowed_bindings.join(", ")}
                    onChange={(event) =>
                      updateService(service, {
                        allowed_bindings: event.target.value
                          .split(",")
                          .map((value) => value.trim().toLowerCase())
                          .filter(Boolean),
                      })
                    }
                    className="mt-3 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]"
                    placeholder={copy.providersPlaceholder}
                    aria-label={`${LABELS[service]} ${copy.providersPlaceholder}`}
                  />
                </div>
              );
            })}
          </div>
        </section>

        <section className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">
            {copy.safetyLimits}
          </h2>
          <p className="mb-4 text-xs text-[var(--muted-foreground)]">
            {copy.safetyHelp}
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-xs text-[var(--muted-foreground)]">
              {copy.requestsPerMinute}
              <input
                type="number"
                min={1}
                value={policy.limits.byok_requests_per_minute}
                onChange={(event) =>
                  setPolicy({
                    ...policy,
                    limits: {
                      ...policy.limits,
                      byok_requests_per_minute: Math.max(
                        1,
                        Number(event.target.value) || 1,
                      ),
                    },
                  })
                }
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]"
              />
            </label>
            <label className="text-xs text-[var(--muted-foreground)]">
              {copy.maxTokens}
              <input
                type="number"
                min={1}
                value={policy.limits.max_single_request_tokens}
                onChange={(event) =>
                  setPolicy({
                    ...policy,
                    limits: {
                      ...policy.limits,
                      max_single_request_tokens: Math.max(
                        1,
                        Number(event.target.value) || 1,
                      ),
                    },
                  })
                }
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]"
              />
            </label>
            <label className="text-xs text-[var(--muted-foreground)]">
              {copy.maxMineruPages}
              <input
                type="number"
                min={1}
                value={policy.limits.max_pages_per_file}
                onChange={(event) =>
                  setPolicy({
                    ...policy,
                    limits: {
                      ...policy.limits,
                      max_pages_per_file: Math.max(
                        1,
                        Number(event.target.value) || 1,
                      ),
                    },
                  })
                }
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]"
              />
            </label>
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">
            {copy.endpointAllowlist}
          </h2>
          <p className="mb-3 text-xs text-[var(--muted-foreground)]">
            {copy.endpointHelp}
          </p>
          <textarea
            value={endpointAllowlistText}
            onChange={(event) => setEndpointAllowlistText(event.target.value)}
            rows={4}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)]"
            aria-label={copy.endpointAllowlist}
          />
        </section>
        {message ? (
          <p className="mt-4 text-sm text-[var(--muted-foreground)]">
            {message}
          </p>
        ) : null}
      </div>
    </main>
  );
}
