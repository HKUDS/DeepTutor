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
import type {
  ByokProfile,
  ByokService,
  ByokSource,
  ByokStatus,
} from "@/features/byok/types";

const NEW_PROFILE = "__new_profile__";

const SERVICE_META: Record<
  ByokService,
  { zh: string; en: string; provider: string; model: string }
> = {
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

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function profileLabel(profile: ByokProfile, fallback: string): string {
  if (profile.name?.trim()) return profile.name.trim();
  return [profile.provider, profile.model].filter(Boolean).join(" · ") || fallback;
}

export default function ByokSettingsPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const copy = zh
    ? {
        accessDenied: "管理员尚未授权你使用此类 BYOK。",
        addProfile: "添加新配置",
        apiKey: "API key / token",
        cloudApiOnly: "仅支持 Cloud API",
        delete: "删除配置",
        deleteConfirm: "确定删除此 BYOK 配置？此操作无法撤销。",
        deleted: "已删除配置。",
        dimension: "维度（可选）",
        endpoint: "端点 URL（可选）",
        globalDisabled:
          "管理员已全局关闭 BYOK。已有配置会保留，但在重新启用前不能使用或修改。",
        headerDescription:
          "使用自己的 LLM、Embedding 或 MinerU Cloud key。密钥仅加密保存在服务端。",
        loadFailed: "无法读取 BYOK 设置",
        loading: "正在加载 BYOK 设置…",
        model: "模型",
        name: "配置名称（可选）",
        namePlaceholder: "例如：工作 OpenAI",
        noPlatform: "无可用平台资源",
        platform: "平台资源",
        profileCount: (count: number) => `已保存 ${count} 个配置`,
        profileSelector: "选择要编辑的配置",
        provider: "Provider",
        replaceKey: "替换 key（留空则保留原值）",
        resourceSource: "资源来源",
        retry: "重试",
        save: "保存我的 key",
        saveFailed: "保存失败",
        saved: "已保存，密钥不会再次显示。",
        serverSideRequest: "由服务端发起请求",
        serviceDisabled: "管理员已关闭此类 BYOK。",
        sourcePlatform: "平台资源",
        title: "BYOK",
        update: "更新配置",
        useProfile: "使用此配置",
        vaultUnavailable: "管理员尚未配置 BYOK Vault 主密钥。",
        usingProfile: "正在使用此配置",
      }
    : {
        accessDenied: "Your administrator has not granted BYOK access for this service.",
        addProfile: "Add a new profile",
        apiKey: "API key / token",
        cloudApiOnly: "Cloud API only",
        delete: "Delete profile",
        deleteConfirm: "Delete this BYOK profile? This cannot be undone.",
        deleted: "Profile deleted.",
        dimension: "Dimension (optional)",
        endpoint: "Endpoint URL (optional)",
        globalDisabled:
          "BYOK is disabled globally by the administrator. Existing profiles remain stored, but cannot be used or changed until it is re-enabled.",
        headerDescription:
          "Use your own LLM, Embedding, or MinerU Cloud key. Secrets stay encrypted on the server.",
        loadFailed: "Unable to load BYOK settings",
        loading: "Loading BYOK settings…",
        model: "Model",
        name: "Profile name (optional)",
        namePlaceholder: "For example, Work OpenAI",
        noPlatform: "No platform resource available",
        platform: "Platform resource",
        profileCount: (count: number) => `${count} saved profile${count === 1 ? "" : "s"}`,
        profileSelector: "Choose a profile to edit",
        provider: "Provider",
        replaceKey: "Replace key (leave blank to keep)",
        resourceSource: "Resource source",
        retry: "Retry",
        save: "Save my key",
        saveFailed: "Unable to save the profile",
        saved: "Saved. The secret will not be shown again.",
        serverSideRequest: "Server-side request",
        serviceDisabled: "BYOK is disabled for this service.",
        sourcePlatform: "Platform resource",
        title: "BYOK",
        update: "Update profile",
        useProfile: "Use this profile",
        vaultUnavailable: "The administrator has not configured the BYOK Vault key.",
        usingProfile: "Using this profile",
      };
  const [status, setStatus] = useState<ByokStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<ByokService | null>(null);
  const [message, setMessage] = useState("");
  const [selectedProfileIds, setSelectedProfileIds] = useState<
    Partial<Record<ByokService, string>>
  >({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    fetchByokStatus()
      .then((next) => {
        if (!cancelled) setStatus(next);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(errorMessage(error, copy.loadFailed));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [copy.loadFailed, loadAttempt]);

  async function reload() {
    const next = await fetchByokStatus();
    setStatus(next);
  }

  const profilesByService = useMemo(() => {
    const map: Record<ByokService, ByokProfile[]> = {
      llm: [],
      embedding: [],
      mineru: [],
    };
    for (const profile of status?.profiles || []) map[profile.service].push(profile);
    return map;
  }, [status]);

  async function save(
    service: ByokService,
    profile: ByokProfile | undefined,
    form: HTMLFormElement,
  ) {
    const data = new FormData(form);
    setBusy(service);
    setMessage("");
    try {
      const saved = await saveByokProfile({
        profileId: profile?.id,
        service,
        provider: String(data.get("provider") || ""),
        name: String(data.get("name") || ""),
        model: String(data.get("model") || ""),
        baseUrl: String(data.get("base_url") || ""),
        dimension: Number(data.get("dimension") || 0),
        mode: service === "mineru" ? "cloud" : "",
        // Existing profile updates always carry their generation so a stale
        // editor receives the server's conflict response instead of overwriting.
        generation: profile?.generation,
        secret: String(data.get("secret") || ""),
      });
      setSelectedProfileIds((current) => ({ ...current, [service]: saved.id }));
      await reload();
      setMessage(copy.saved);
    } catch (error) {
      setMessage(errorMessage(error, copy.saveFailed));
    } finally {
      setBusy(null);
    }
  }

  async function changeSource(
    service: ByokService,
    source: ByokSource,
    profileId?: string,
  ) {
    setBusy(service);
    setMessage("");
    try {
      await setByokPreference(service, source, profileId);
      await reload();
    } catch (error) {
      setMessage(errorMessage(error, zh ? "切换来源失败" : "Unable to change resource source"));
    } finally {
      setBusy(null);
    }
  }

  async function remove(service: ByokService, profile: ByokProfile) {
    if (!window.confirm(copy.deleteConfirm)) return;
    setBusy(service);
    setMessage("");
    try {
      await deleteByokProfile(profile.id);
      setSelectedProfileIds((current) => ({
        ...current,
        [service]: NEW_PROFILE,
      }));
      await reload();
      setMessage(copy.deleted);
    } catch (error) {
      setMessage(errorMessage(error, zh ? "删除失败" : "Unable to delete the profile"));
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
          <h1 className="text-xl font-semibold text-[var(--foreground)]">
            {copy.title}
          </h1>
          <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {copy.headerDescription}
          </p>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="animate-spin" size={18} />
          {copy.loading}
        </div>
      ) : !status ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">
          <p>{loadError || copy.loadFailed}</p>
          <button
            type="button"
            onClick={() => setLoadAttempt((current) => current + 1)}
            className="mt-2 rounded-lg border border-current px-3 py-1.5 text-xs font-medium"
          >
            {copy.retry}
          </button>
        </div>
      ) : (
        <>
          {!status.vault_available ? (
            <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
              {copy.vaultUnavailable}
            </div>
          ) : null}
          {!status.policy.enabled ? (
            <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">
              {copy.globalDisabled}
            </div>
          ) : null}
          {message ? (
            <p className="mb-4 text-sm text-[var(--muted-foreground)]">{message}</p>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-3">
            {(["llm", "embedding", "mineru"] as ByokService[]).map(
              (service) => {
                const meta = SERVICE_META[service];
                const info = status.policy.services[service];
                const profiles = profilesByService[service];
                const preference = status.preferences[service];
                const platform = status.platform[service];
                const requestedProfileId = selectedProfileIds[service];
                const preferredProfile = profiles.find(
                  (profile) => profile.id === preference?.profile_id,
                );
                const requestedProfile = profiles.find(
                  (profile) => profile.id === requestedProfileId,
                );
                const selectedProfile =
                  requestedProfileId === NEW_PROFILE
                    ? undefined
                    : requestedProfile || preferredProfile || profiles[0];
                const selectedProfileId =
                  requestedProfileId === NEW_PROFILE
                    ? NEW_PROFILE
                    : selectedProfile?.id || NEW_PROFILE;
                const unavailableReason = !status.policy.enabled
                  ? copy.globalDisabled
                  : !info?.enabled
                    ? copy.serviceDisabled
                    : !info?.allowed
                      ? copy.accessDenied
                      : null;
                const formDisabled = Boolean(unavailableReason) ||
                  busy === service ||
                  !status.vault_available;
                const selectedIsActive =
                  preference?.source === "byok" &&
                  preference.profile_id === selectedProfile?.id;

                return (
                  <section
                    key={service}
                    className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-4"
                  >
                    <div className="mb-4 flex items-center justify-between gap-2">
                      <div>
                        <h2 className="font-medium text-[var(--foreground)]">
                          {zh ? meta.zh : meta.en}
                        </h2>
                        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                          {service === "mineru"
                            ? copy.cloudApiOnly
                            : copy.serverSideRequest}
                        </p>
                      </div>
                      {selectedIsActive ? (
                        <Check size={16} className="text-emerald-500" />
                      ) : null}
                    </div>

                    {unavailableReason ? (
                      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                        {unavailableReason}
                      </p>
                    ) : (
                      <>
                        <label className="mb-2 block text-[11px] text-[var(--muted-foreground)]">
                          {copy.profileSelector}
                          <select
                            value={selectedProfileId}
                            disabled={busy === service}
                            onChange={(event) =>
                              setSelectedProfileIds((current) => ({
                                ...current,
                                [service]: event.target.value,
                              }))
                            }
                            className={`${INPUT_CLASS} mt-1`}
                          >
                            <option value={NEW_PROFILE}>{copy.addProfile}</option>
                            {profiles.map((profile) => (
                              <option key={profile.id} value={profile.id}>
                                {profileLabel(profile, zh ? "未命名配置" : "Unnamed profile")}
                              </option>
                            ))}
                          </select>
                        </label>
                        <p className="mb-3 text-[11px] text-[var(--muted-foreground)]">
                          {copy.profileCount(profiles.length)}
                        </p>

                        <form
                          key={`${service}:${selectedProfile?.id ?? NEW_PROFILE}:${selectedProfile?.generation ?? "new"}`}
                          onSubmit={(event) => {
                            event.preventDefault();
                            void save(service, selectedProfile, event.currentTarget);
                          }}
                          className="space-y-2.5"
                        >
                          <input
                            name="name"
                            defaultValue={selectedProfile?.name || ""}
                            placeholder={copy.namePlaceholder}
                            aria-label={copy.name}
                            className={INPUT_CLASS}
                          />
                          <input
                            name="provider"
                            defaultValue={selectedProfile?.provider || meta.provider}
                            placeholder={copy.provider}
                            aria-label={copy.provider}
                            className={INPUT_CLASS}
                          />
                          <input
                            name="model"
                            defaultValue={selectedProfile?.model || meta.model}
                            placeholder={copy.model}
                            aria-label={copy.model}
                            className={INPUT_CLASS}
                          />
                          {service !== "mineru" ? (
                            <input
                              name="base_url"
                              defaultValue={selectedProfile?.base_url || ""}
                              placeholder={copy.endpoint}
                              aria-label={copy.endpoint}
                              className={INPUT_CLASS}
                            />
                          ) : null}
                          {service === "embedding" ? (
                            <input
                              name="dimension"
                              type="number"
                              min={0}
                              defaultValue={selectedProfile?.dimension || 0}
                              placeholder={copy.dimension}
                              aria-label={copy.dimension}
                              className={INPUT_CLASS}
                            />
                          ) : null}
                          <input
                            name="secret"
                            type="password"
                            autoComplete="new-password"
                            required={!selectedProfile}
                            placeholder={selectedProfile ? copy.replaceKey : copy.apiKey}
                            aria-label={selectedProfile ? copy.replaceKey : copy.apiKey}
                            className={INPUT_CLASS}
                          />
                          <button
                            type="submit"
                            disabled={formDisabled}
                            className="w-full rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs font-medium text-[var(--background)] disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            {busy === service ? (
                              <Loader2 size={14} className="mx-auto animate-spin" />
                            ) : selectedProfile ? (
                              copy.update
                            ) : (
                              copy.save
                            )}
                          </button>
                        </form>

                        <div className="mt-4 border-t border-[var(--border)]/60 pt-3">
                          <p className="mb-2 text-[11px] text-[var(--muted-foreground)]">
                            {copy.resourceSource}
                          </p>
                          <div className="flex gap-1.5">
                            <button
                              type="button"
                              disabled={formDisabled || !selectedProfile}
                              onClick={() =>
                                selectedProfile &&
                                void changeSource(
                                  service,
                                  "byok",
                                  selectedProfile.id,
                                )
                              }
                              className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] ${
                                selectedIsActive
                                  ? "border-emerald-500/50 bg-emerald-500/10"
                                  : "border-[var(--border)]"
                              }`}
                            >
                              {selectedIsActive ? copy.usingProfile : copy.useProfile}
                            </button>
                            <button
                              type="button"
                              disabled={
                                Boolean(unavailableReason) ||
                                busy === service ||
                                !platform
                              }
                              onClick={() =>
                                void changeSource(service, "platform")
                              }
                              className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] ${
                                preference?.source === "platform"
                                  ? "border-blue-500/50 bg-blue-500/10"
                                  : "border-[var(--border)]"
                              }`}
                            >
                              {platform ? copy.sourcePlatform : copy.noPlatform}
                            </button>
                          </div>
                        </div>
                        {selectedProfile ? (
                          <button
                            type="button"
                            onClick={() => void remove(service, selectedProfile)}
                            disabled={busy === service}
                            className="mt-3 inline-flex items-center gap-1 text-[11px] text-red-500 disabled:opacity-45"
                          >
                            <Trash2 size={12} /> {copy.delete}
                          </button>
                        ) : null}
                      </>
                    )}
                  </section>
                );
              },
            )}
          </div>
        </>
      )}
    </div>
  );
}
