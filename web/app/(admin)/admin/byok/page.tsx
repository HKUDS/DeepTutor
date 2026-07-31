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

const SERVICES = ["llm", "embedding", "mineru"] as const;
type Service = (typeof SERVICES)[number];

const LABELS: Record<Service, string> = {
  llm: "LLM",
  embedding: "Embedding",
  mineru: "MinerU",
};

export default function AdminByokPage() {
  const router = useRouter();
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [policy, setPolicy] = useState<AdminByokPolicy | null>(null);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [vaultAvailable, setVaultAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

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
      fetchAdminByokPolicy()
        .then((data) => {
          setPolicy(data.policy);
          setAuthEnabled(data.auth_enabled);
          setVaultAvailable(data.vault_available);
        })
        .catch((error) => setMessage(error instanceof Error ? error.message : "无法读取 BYOK 策略"))
        .finally(() => setLoading(false));
    });
  }, [router]);

  function updateService(service: Service, patch: Partial<AdminByokPolicy["services"][Service]>) {
    setPolicy((current) =>
      current
        ? { ...current, services: { ...current.services, [service]: { ...current.services[service], ...patch } } }
        : current,
    );
  }

  async function save() {
    if (!policy) return;
    setSaving(true);
    setMessage("");
    try {
      setPolicy(await saveAdminByokPolicy(policy));
      setMessage(zh ? "已保存" : "Saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading || !policy) {
    return <div className="flex min-h-screen items-center justify-center text-[var(--muted-foreground)]"><Loader2 className="animate-spin" size={18} /></div>;
  }

  return (
    <main className="min-h-screen bg-[var(--background)] px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <Link href="/admin/users" className="mb-5 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
          <ArrowLeft size={16} /> {zh ? "返回用户管理" : "Back to users"}
        </Link>
        <div className="mb-6 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-xl bg-fuchsia-500/10 p-2.5 text-fuchsia-600 dark:text-fuchsia-400"><KeyRound size={20} /></div>
            <div>
              <h1 className="text-xl font-semibold text-[var(--foreground)]">BYOK policy</h1>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">{zh ? "控制全局 BYOK、provider 白名单和运行安全上限。不会显示任何用户密钥。" : "Control global BYOK, provider allowlists, and safety limits. User secrets are never shown."}</p>
            </div>
          </div>
          <button type="button" onClick={() => void save()} disabled={saving} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs font-medium text-[var(--background)] disabled:opacity-50"><Save size={14} /> {saving ? "Saving…" : "Save"}</button>
        </div>

        {!authEnabled ? <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">BYOK is fail-closed until auth.enabled=true.</div> : null}
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <div className={`rounded-xl border px-4 py-3 text-sm ${vaultAvailable ? "border-emerald-500/30 bg-emerald-500/10" : "border-amber-500/30 bg-amber-500/10"}`}><span className="font-medium">Vault</span><span className="ml-2 text-[var(--muted-foreground)]">{vaultAvailable ? "ready" : "master key missing"}</span></div>
          <label className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--foreground)]"><span>Global BYOK</span><input type="checkbox" checked={policy.enabled} onChange={(event) => setPolicy({ ...policy, enabled: event.target.checked })} /></label>
        </div>

        <section className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">Service policy</h2>
          <p className="mb-4 text-xs text-[var(--muted-foreground)]">The user grant must also allow BYOK. Platform quotas and sandbox limits remain separate.</p>
          <div className="space-y-3">
            {SERVICES.map((service) => {
              const item = policy.services[service];
              return <div key={service} className="rounded-xl border border-[var(--border)]/70 p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm font-medium text-[var(--foreground)]">{LABELS[service]}</span>
                  <div className="flex items-center gap-3 text-xs text-[var(--muted-foreground)]">
                    <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={item.enabled} onChange={(event) => updateService(service, { enabled: event.target.checked })} /> enabled</label>
                    {service === "mineru" ? <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={item.allow_cloud !== false} onChange={(event) => updateService(service, { allow_cloud: event.target.checked })} /> cloud</label> : <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={item.allow_custom_endpoints === true} onChange={(event) => updateService(service, { allow_custom_endpoints: event.target.checked })} /> custom endpoint</label>}
                  </div>
                </div>
                <input value={item.allowed_bindings.join(", ")} onChange={(event) => updateService(service, { allowed_bindings: event.target.value.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean) })} className="mt-3 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]" placeholder="Allowed providers, comma separated" />
              </div>;
            })}
          </div>
        </section>

        <section className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">Safety limits</h2>
          <p className="mb-4 text-xs text-[var(--muted-foreground)]">These limits apply to BYOK too; zero is not treated as unlimited here.</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-xs text-[var(--muted-foreground)]">BYOK requests/min<input type="number" min={1} value={policy.limits.byok_requests_per_minute} onChange={(event) => setPolicy({ ...policy, limits: { ...policy.limits, byok_requests_per_minute: Math.max(1, Number(event.target.value) || 1) } })} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]" /></label>
            <label className="text-xs text-[var(--muted-foreground)]">Max LLM tokens/request<input type="number" min={1} value={policy.limits.max_single_request_tokens} onChange={(event) => setPolicy({ ...policy, limits: { ...policy.limits, max_single_request_tokens: Math.max(1, Number(event.target.value) || 1) } })} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]" /></label>
            <label className="text-xs text-[var(--muted-foreground)]">Max MinerU pages/file<input type="number" min={1} value={policy.limits.max_pages_per_file} onChange={(event) => setPolicy({ ...policy, limits: { ...policy.limits, max_pages_per_file: Math.max(1, Number(event.target.value) || 1) } })} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)]" /></label>
          </div>
        </section>

        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">Endpoint allowlist</h2>
          <p className="mb-3 text-xs text-[var(--muted-foreground)]">One exact HTTPS URL per line. Private, loopback and metadata addresses remain blocked.</p>
          <textarea value={policy.endpoint_allowlist.join("\n")} onChange={(event) => setPolicy({ ...policy, endpoint_allowlist: event.target.value.split(/\n+/).map((value) => value.trim().replace(/\/$/, "")).filter(Boolean) })} rows={4} className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)]" />
        </section>
        {message ? <p className="mt-4 text-sm text-[var(--muted-foreground)]">{message}</p> : null}
      </div>
    </main>
  );
}
