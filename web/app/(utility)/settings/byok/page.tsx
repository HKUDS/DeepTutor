"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, KeyRound, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import SettingsBreadcrumb from "@/components/settings/SettingsBreadcrumb";
import {
  deleteByokProfile,
  fetchByokStatus,
  saveByokProfile,
  setByokPreference,
} from "@/features/byok/api";
import type { ByokProfile, ByokService, ByokSource, ByokStatus } from "@/features/byok/types";

const SERVICE_META: Record<ByokService, { zh: string; en: string; provider: string; model: string }> = {
  llm: { zh: "LLM", en: "LLM", provider: "openai", model: "gpt-4o-mini" },
  embedding: {
    zh: "Embedding",
    en: "Embedding",
    provider: "openai",
    model: "text-embedding-3-small",
  },
  mineru: { zh: "MinerU", en: "MinerU", provider: "mineru", model: "pipeline" },
};

const INPUT_CLASS =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--foreground)] outline-none transition focus:border-violet-500/60";

export default function ByokSettingsPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [status, setStatus] = useState<ByokStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<ByokService | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchByokStatus()
      .then(setStatus)
      .catch((error) => setMessage(error instanceof Error ? error.message : "无法读取 BYOK 配置"))
      .finally(() => setLoading(false));
  }, []);

  const reload = async () => {
    setStatus(await fetchByokStatus());
  };

  const profilesByService = useMemo(() => {
    const map: Record<ByokService, ByokProfile[]> = { llm: [], embedding: [], mineru: [] };
    for (const profile of status?.profiles || []) map[profile.service].push(profile);
    return map;
  }, [status]);

  async function save(service: ByokService, form: HTMLFormElement) {
    const data = new FormData(form);
    setBusy(service);
    setMessage("");
    try {
      await saveByokProfile({
        profileId: String(data.get("profile_id") || "") || undefined,
        service,
        provider: String(data.get("provider") || ""),
        name: String(data.get("name") || ""),
        model: String(data.get("model") || ""),
        baseUrl: String(data.get("base_url") || ""),
        dimension: Number(data.get("dimension") || 0),
        mode: service === "mineru" ? "cloud" : "",
        generation: Number(data.get("generation") || 0) || undefined,
        secret: String(data.get("secret") || ""),
      });
      await reload();
      form.reset();
      setMessage(zh ? "已保存，密钥不会再次显示。" : "Saved. The secret will not be shown again.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function changeSource(service: ByokService, source: ByokSource, profileId?: string) {
    setBusy(service);
    setMessage("");
    try {
      await setByokPreference(service, source, profileId);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "切换来源失败");
    } finally {
      setBusy(null);
    }
  }

  async function remove(service: ByokService, profileId: string) {
    setBusy(service);
    try {
      await deleteByokProfile(profileId);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl pb-12">
      <SettingsBreadcrumb />
      <header className="mb-6 mt-5 flex items-start gap-3">
        <div className="rounded-xl bg-violet-500/10 p-2.5 text-violet-600 dark:text-violet-400">
          <KeyRound size={20} />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-[var(--foreground)]">BYOK</h1>
          <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {zh
              ? "使用自己的 LLM、Embedding 或 MinerU Cloud key。密钥仅加密保存在服务端。"
              : "Use your own LLM, Embedding, or MinerU Cloud key. Secrets stay encrypted on the server."}
          </p>
        </div>
      </header>

      {loading ? <Loader2 className="animate-spin text-[var(--muted-foreground)]" size={18} /> : null}
      {status && !status.vault_available ? (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          {zh ? "管理员尚未配置 BYOK Vault 主密钥。" : "The administrator has not configured the BYOK Vault key."}
        </div>
      ) : null}
      {message ? <p className="mb-4 text-sm text-[var(--muted-foreground)]">{message}</p> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        {(["llm", "embedding", "mineru"] as ByokService[]).map((service) => {
          const meta = SERVICE_META[service];
          const info = status?.policy.services[service];
          const profiles = profilesByService[service];
          const preference = status?.preferences[service];
          const platform = status?.platform[service];
          const disabled = !info?.enabled || !info?.allowed || busy === service;
          const profile = profiles[0];
          return (
            <section key={service} className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4">
              <div className="mb-4 flex items-center justify-between gap-2">
                <div>
                  <h2 className="font-medium text-[var(--foreground)]">{zh ? meta.zh : meta.en}</h2>
                  <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                    {service === "mineru" ? "Cloud API only" : "Server-side request"}
                  </p>
                </div>
                {preference?.source === "byok" ? <Check size={16} className="text-emerald-500" /> : null}
              </div>

              {!info?.allowed ? (
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {zh ? "管理员暂未开放此类 BYOK。" : "BYOK is not enabled for this service."}
                </p>
              ) : (
                <>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void save(service, event.currentTarget);
                    }}
                    className="space-y-2.5"
                  >
                    <input type="hidden" name="profile_id" value={profile?.id || ""} readOnly />
                    <input type="hidden" name="generation" value={profile?.generation || ""} readOnly />
                    <input name="provider" defaultValue={profile?.provider || meta.provider} placeholder="Provider" className={INPUT_CLASS} />
                    <input name="model" defaultValue={profile?.model || meta.model} placeholder="Model" className={INPUT_CLASS} />
                    {service !== "mineru" ? (
                      <input name="base_url" defaultValue={profile?.base_url || ""} placeholder="Endpoint URL (optional)" className={INPUT_CLASS} />
                    ) : null}
                    {service === "embedding" ? (
                      <input name="dimension" type="number" min={0} defaultValue={profile?.dimension || 0} placeholder="Dimension" className={INPUT_CLASS} />
                    ) : null}
                    <input name="secret" type="password" autoComplete="new-password" placeholder={profile ? "Replace key (leave blank to keep)" : "API key / token"} className={INPUT_CLASS} />
                    <button type="submit" disabled={disabled || !status?.vault_available} className="w-full rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs font-medium text-[var(--background)] disabled:cursor-not-allowed disabled:opacity-45">
                      {busy === service ? <Loader2 size={14} className="mx-auto animate-spin" /> : profile ? "更新配置" : "保存我的 key"}
                    </button>
                  </form>

                  <div className="mt-4 border-t border-[var(--border)]/60 pt-3">
                    <p className="mb-2 text-[11px] text-[var(--muted-foreground)]">资源来源</p>
                    <div className="flex gap-1.5">
                      <button type="button" disabled={disabled || !profile} onClick={() => void changeSource(service, "byok", profile?.id)} className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] ${preference?.source === "byok" ? "border-emerald-500/50 bg-emerald-500/10" : "border-[var(--border)]"}`}>我的 key</button>
                      <button type="button" disabled={busy === service || !platform} onClick={() => void changeSource(service, "platform")} className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] ${preference?.source === "platform" ? "border-blue-500/50 bg-blue-500/10" : "border-[var(--border)]"}`}>平台资源</button>
                    </div>
                  </div>
                  {profile ? (
                    <button type="button" onClick={() => void remove(service, profile.id)} disabled={busy === service} className="mt-3 inline-flex items-center gap-1 text-[11px] text-red-500 disabled:opacity-45">
                      <Trash2 size={12} /> 删除配置
                    </button>
                  ) : null}
                </>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
