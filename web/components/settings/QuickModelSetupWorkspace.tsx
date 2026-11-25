"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  SlidersHorizontal,
  Zap,
} from "lucide-react";

import ProviderIcon from "@/components/common/ProviderIcon";
import { apiFetch, apiUrl } from "@/lib/api";
import { randomUuid } from "@/lib/random-uuid";
import { flattenModels } from "@/lib/provider-registry";
import {
  useSettings,
  type CatalogConnection,
  type CatalogProfile,
  type ConnectionTarget,
  type Discovery,
  type ServiceName,
} from "@/features/settings/store/SettingsStore";
import {
  FEATURED_DOMESTIC_PROVIDERS,
  MORE_PROVIDERS,
  SYNCABLE_EXTRA_SERVICES,
  findQuickPreset,
  formatFriendlySetupError,
  pickRecommendedModel,
  type FriendlyErrorResult,
  type QuickProviderPreset,
} from "@/lib/quick-setup-presets";
import { inputClass, selectClass } from "./shared";

type SetupResultState = {
  providerId: string;
  providerLabel: string;
  connectionId: string;
  connection: CatalogConnection;
  modelName: string;
  discoveredModels: string[];
  profileId: string;
  modelEntryId: string;
};

function hasActiveService(
  services: Record<
    ServiceName,
    {
      active_profile_id: string | null;
      active_model_id?: string | null;
      profiles: CatalogProfile[];
    }
  >,
  service: ServiceName,
): boolean {
  const bucket = services[service];
  if (!bucket?.active_profile_id) return false;
  const profile = bucket.profiles.find((p) => p.id === bucket.active_profile_id);
  if (!profile) return false;
  if (service === "search") return true;
  return Boolean(
    profile.models?.some(
      (m) => m.id === bucket.active_model_id && Boolean(m.model?.trim()),
    ),
  );
}

export function QuickModelSetupWorkspace() {
  const { t } = useTranslation();

  const {
    catalog,
    connectionTargets,
    providers,
    catalogEditable,
    reloadSettings,
  } = useSettings();

  const llmRows = useMemo(() => flattenModels(catalog, ["llm"]), [catalog]);
  const activeLlm = useMemo(
    () =>
      llmRows.find(
        (row) =>
          row.profile.id === catalog.services.llm.active_profile_id &&
          row.model?.id === catalog.services.llm.active_model_id,
      ) ?? null,
    [
      llmRows,
      catalog.services.llm.active_profile_id,
      catalog.services.llm.active_model_id,
    ],
  );
  const hasConfiguredLlm = Boolean(activeLlm);

  const [showAddForm, setShowAddForm] = useState(!hasConfiguredLlm);
  const [selectedVendorId, setSelectedVendorId] = useState<string>("deepseek");
  const [showMoreVendors, setShowMoreVendors] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [manualModel, setManualModel] = useState("");
  const [showModelPicker, setShowModelPicker] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [switchingActive, setSwitchingActive] = useState(false);
  const [errorState, setErrorState] = useState<FriendlyErrorResult | null>(null);
  const [showRawError, setShowRawError] = useState(false);

  const [setupResult, setSetupResult] = useState<SetupResultState | null>(null);
  const [selectedSyncServices, setSelectedSyncServices] = useState<ServiceName[]>(
    [],
  );
  const [syncingExtras, setSyncingExtras] = useState(false);
  const [syncedServices, setSyncedServices] = useState<ServiceName[]>([]);

  const targetByProvider = useMemo(() => {
    const map = new Map<string, ConnectionTarget>();
    for (const target of connectionTargets) {
      map.set(target.provider, target);
    }
    return map;
  }, [connectionTargets]);

  const selectedPreset: QuickProviderPreset =
    findQuickPreset(selectedVendorId) ?? FEATURED_DOMESTIC_PROVIDERS[0];

  const selectedTarget = targetByProvider.get(selectedPreset.id);

  const resolveDefaultBaseUrl = (vendorId: string): string => {
    if (vendorId === "custom") return customBaseUrl.trim();
    const targetUrl = targetByProvider.get(vendorId)?.default_base_url;
    if (targetUrl) return targetUrl;
    const llmOpt = providers.llm?.find((p) => p.value === vendorId);
    return llmOpt?.base_url ?? "";
  };

  const getSyncableCapabilities = (vendorId: string): ServiceName[] => {
    const target = targetByProvider.get(vendorId);
    if (!target) return [];
    return SYNCABLE_EXTRA_SERVICES.map((item) => item.service).filter((svc) =>
      Boolean(target.services[svc]),
    );
  };

  const handleSelectVendor = (vendorId: string) => {
    setSelectedVendorId(vendorId);
    setErrorState(null);
    setShowRawError(false);
    setSetupResult(null);
    setSyncedServices([]);
    const preset = findQuickPreset(vendorId);
    setManualModel(preset?.recommendedModels[0] ?? "");
  };

  const handleQuickConnect = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!catalogEditable || submitting) return;

    const trimmedKey = apiKey.trim();
    const baseUrl = resolveDefaultBaseUrl(selectedPreset.id);

    if (!trimmedKey) {
      setErrorState({
        titleKey: "quickSetup.error.missingKeyTitle",
        detailKey: "quickSetup.error.missingKeyDetail",
      });
      return;
    }

    if (selectedPreset.requiresBaseUrl && !baseUrl) {
      setErrorState({
        titleKey: "quickSetup.error.missingUrlTitle",
        detailKey: "quickSetup.error.missingUrlDetail",
      });
      return;
    }

    setSubmitting(true);
    setErrorState(null);
    setShowRawError(false);

    try {
      const probeRes = await apiFetch(apiUrl("/api/settings/test-provider"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: "llm",
          binding: selectedPreset.id,
          base_url: baseUrl,
          api_key: trimmedKey,
          api_format: "auto",
        }),
      });
      const probePayload = (await probeRes.json().catch(() => ({}))) as Discovery & {
        detail?: string;
      };

      if (!probeRes.ok || probePayload.status !== "connected") {
        setErrorState(
          formatFriendlySetupError(
            probePayload,
            typeof probePayload.detail === "string"
              ? probePayload.detail
              : probePayload.warning,
          ),
        );
        return;
      }

      const discoveredIds = (probePayload.models ?? [])
        .filter((m) => !m.services?.length || m.services.includes("llm"))
        .map((m) => m.id.trim())
        .filter(Boolean);

      const chosenModel =
        manualModel.trim() || pickRecommendedModel(selectedPreset, discoveredIds);

      if (!chosenModel) {
        setErrorState({
          titleKey: "quickSetup.error.missingModelTitle",
          detailKey: "quickSetup.error.missingModelDetail",
        });
        setShowModelPicker(true);
        return;
      }

      const connectionId = `conn-${randomUuid().slice(0, 8)}`;
      const profileId = `llm-${randomUuid().slice(0, 8)}`;
      const modelEntryId = `model-${randomUuid().slice(0, 8)}`;
      const displayName = t(selectedPreset.nameKey);

      const connection: CatalogConnection = {
        id: connectionId,
        name: displayName,
        provider: selectedPreset.id,
        api_key: trimmedKey,
        base_url: baseUrl,
        api_version: "",
        api_format: "auto",
        discovery: {
          ...probePayload,
          checked_at: new Date().toISOString(),
        },
      };

      const llmProfile: CatalogProfile = {
        id: profileId,
        name: displayName,
        binding: selectedPreset.id,
        connection_id: connectionId,
        base_url: baseUrl,
        api_key: trimmedKey,
        api_version: "",
        api_format: "auto",
        models: [
          {
            id: modelEntryId,
            name: chosenModel,
            model: chosenModel,
          },
        ],
      };

      const applyRes = await apiFetch(apiUrl("/api/settings/apply/provider"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: "llm",
          profile: llmProfile,
          connection,
          activate: true,
          active_model_id: modelEntryId,
        }),
      });
      const applyPayload = await applyRes.json().catch(() => ({}));
      if (!applyRes.ok) {
        throw new Error(
          typeof applyPayload.detail === "string"
            ? applyPayload.detail
            : `HTTP ${applyRes.status}`,
        );
      }

      if (!catalog.services.task?.mode || catalog.services.task.mode === "profiles") {
        const hasExplicitTask = hasActiveService(catalog.services, "task");
        if (!hasExplicitTask) {
          await apiFetch(apiUrl("/api/settings/apply/registry"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: "task_choice",
              task: { mode: "inherit" },
            }),
          }).catch(() => {});
        }
      }

      await reloadSettings();

      const extraCandidates = getSyncableCapabilities(selectedPreset.id).filter(
        (svc) => !hasActiveService(catalog.services, svc),
      );
      setSelectedSyncServices(extraCandidates);
      setSyncedServices([]);
      setSetupResult({
        providerId: selectedPreset.id,
        providerLabel: displayName,
        connectionId,
        connection,
        modelName: chosenModel,
        discoveredModels: discoveredIds,
        profileId,
        modelEntryId,
      });
      setApiKey("");
    } catch (error) {
      setErrorState(
        formatFriendlySetupError(
          null,
          error instanceof Error ? error.message : String(error),
        ),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleSyncExtraServices = async (
    targetProviderId: string,
    connectionId: string,
    connectionName: string,
    servicesToSync: ServiceName[],
  ) => {
    if (!servicesToSync.length || syncingExtras) return;
    const target = targetByProvider.get(targetProviderId);
    if (!target) return;

    setSyncingExtras(true);
    const newlySynced: ServiceName[] = [];
    try {
      for (const svc of servicesToSync) {
        const svcSpec = target.services[svc];
        if (!svcSpec || !svcSpec.default_model) continue;

        const profileId = `${svc}-${randomUuid().slice(0, 8)}`;
        const modelEntryId = `model-${randomUuid().slice(0, 8)}`;
        const modelEntry: CatalogProfile["models"][number] = {
          id: modelEntryId,
          name: svcSpec.default_model,
          model: svcSpec.default_model,
          ...(svc === "embedding" && svcSpec.default_dim
            ? { dimension: String(svcSpec.default_dim) }
            : {}),
          ...(svc === "tts" && svcSpec.default_voice
            ? { voice: svcSpec.default_voice }
            : {}),
        };

        const profile: CatalogProfile = {
          id: profileId,
          name: connectionName,
          binding: svcSpec.provider || targetProviderId,
          connection_id: connectionId,
          base_url: svcSpec.base_url || target.default_base_url || "",
          api_key: "***",
          api_version: "",
          models: [modelEntry],
        };

        const res = await apiFetch(apiUrl("/api/settings/apply/provider"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            service: svc,
            profile,
            activate: true,
            active_model_id: modelEntryId,
          }),
        });
        if (res.ok) {
          newlySynced.push(svc);
        }
      }
      if (newlySynced.length > 0) {
        setSyncedServices((prev) => [...new Set([...prev, ...newlySynced])]);
        setSelectedSyncServices((prev) =>
          prev.filter((item) => !newlySynced.includes(item)),
        );
        await reloadSettings();
      }
    } finally {
      setSyncingExtras(false);
    }
  };

  const handleSwitchActiveLlm = async (value: string) => {
    const [profileId, modelId] = value.split("::");
    if (!profileId || !modelId) return;
    setSwitchingActive(true);
    try {
      await apiFetch(apiUrl("/api/settings/apply/registry"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "default",
          service: "llm",
          profile_id: profileId,
          model_id: modelId,
        }),
      });
      await reloadSettings();
    } finally {
      setSwitchingActive(false);
    }
  };

  const handleSwitchModelAfterSetup = async (nextModelName: string) => {
    if (!setupResult || !nextModelName.trim()) return;
    setSubmitting(true);
    try {
      const updatedProfile: CatalogProfile = {
        id: setupResult.profileId,
        name: setupResult.providerLabel,
        binding: setupResult.providerId,
        connection_id: setupResult.connectionId,
        base_url: setupResult.connection.base_url,
        api_key: "***",
        api_version: "",
        api_format: "auto",
        models: [
          {
            id: setupResult.modelEntryId,
            name: nextModelName.trim(),
            model: nextModelName.trim(),
          },
        ],
      };
      const res = await apiFetch(apiUrl("/api/settings/apply/provider"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: "llm",
          profile: updatedProfile,
          activate: true,
          active_model_id: setupResult.modelEntryId,
        }),
      });
      if (res.ok) {
        setSetupResult((prev) =>
          prev ? { ...prev, modelName: nextModelName.trim() } : null,
        );
        await reloadSettings();
      }
    } finally {
      setSubmitting(false);
    }
  };

  const activeConnection = useMemo(() => {
    if (!activeLlm?.profile.connection_id) return null;
    return (
      catalog.connections?.find(
        (c) => c.id === activeLlm.profile.connection_id,
      ) ?? null
    );
  }, [activeLlm, catalog.connections]);

  const activeProviderSyncable = useMemo(() => {
    if (!activeConnection) return [];
    return getSyncableCapabilities(activeConnection.provider).filter(
      (svc) => !hasActiveService(catalog.services, svc),
    );
  }, [activeConnection, catalog.services, targetByProvider]);

  const renderProviderCard = (preset: QuickProviderPreset) => {
    const isSelected = selectedPreset.id === preset.id;
    const syncable = getSyncableCapabilities(preset.id);
    const hasEmbedding = syncable.includes("embedding");
    const hasVoice = syncable.includes("tts") || syncable.includes("stt");

    return (
      <button
        key={preset.id}
        type="button"
        onClick={() => handleSelectVendor(preset.id)}
        className={`group relative flex flex-col justify-between rounded-xl border p-4 text-left transition-all ${
          isSelected
            ? "border-[var(--primary)] bg-[var(--primary)]/[0.06] ring-1 ring-[var(--primary)]"
            : "border-[var(--border)] bg-[var(--card)] hover:border-[var(--foreground)]/30 hover:bg-[var(--accent)]/40"
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--muted)]">
              <ProviderIcon provider={preset.id} size={20} />
            </div>
            <div>
              <div className="text-[14px] font-semibold text-[var(--foreground)]">
                {t(preset.nameKey)}
              </div>
              {preset.badgeKey && (
                <span className="mt-0.5 inline-block rounded-full bg-[var(--primary)]/15 px-2 py-0.5 text-[11px] font-medium text-[var(--primary)]">
                  {t(preset.badgeKey)}
                </span>
              )}
            </div>
          </div>
          {isSelected && (
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)]">
              <Check size={12} strokeWidth={2.5} />
            </span>
          )}
        </div>

        <p className="mt-2.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
          {t(preset.taglineKey)}
        </p>

        {(hasEmbedding || hasVoice) && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {hasEmbedding && (
              <span className="rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-400">
                {t("quickSetup.tag.knowledgeBase")}
              </span>
            )}
            {hasVoice && (
              <span className="rounded-md bg-rose-500/10 px-1.5 py-0.5 text-[11px] text-rose-700 dark:text-rose-400">
                {t("quickSetup.tag.voice")}
              </span>
            )}
          </div>
        )}
      </button>
    );
  };

  return (
    <div className="space-y-6">
      {hasConfiguredLlm && activeLlm && (
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <ProviderIcon
                  provider={activeLlm.profile.binding || "openai"}
                  size={24}
                />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium text-[var(--muted-foreground)]">
                    {t("quickSetup.activeCard.label")}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
                    <CheckCircle2 size={11} />
                    {t("quickSetup.activeCard.ready")}
                  </span>
                </div>
                <div className="mt-0.5 text-base font-semibold text-[var(--foreground)]">
                  {activeLlm.model?.user_name ||
                    activeLlm.model?.name ||
                    activeLlm.model?.model}
                  <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
                    · {activeLlm.profile.name}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {llmRows.length > 1 && (
                <select
                  aria-label={t("quickSetup.activeCard.switchLabel")}
                  disabled={switchingActive || !catalogEditable}
                  value={`${activeLlm.profile.id}::${activeLlm.model?.id ?? ""}`}
                  onChange={(e) => void handleSwitchActiveLlm(e.target.value)}
                  className={`${selectClass} w-auto min-w-[190px] py-1.5 text-[13px]`}
                >
                  {llmRows.map((row) => (
                    <option
                      key={`${row.profile.id}::${row.model?.id ?? ""}`}
                      value={`${row.profile.id}::${row.model?.id ?? ""}`}
                    >
                      {row.model?.user_name ||
                        row.model?.name ||
                        row.model?.model}{" "}
                      ({row.profile.name})
                    </option>
                  ))}
                </select>
              )}

              <Link
                href="/chat"
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
              >
                {t("quickSetup.action.startChat")}
                <ArrowRight size={14} />
              </Link>

              <button
                type="button"
                onClick={() => {
                  setShowAddForm((prev) => !prev);
                  setSetupResult(null);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--accent)]"
              >
                <Plus size={14} />
                {showAddForm
                  ? t("quickSetup.action.hideForm")
                  : t("quickSetup.action.addModel")}
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)]/60 pt-3.5 text-[12px]">
            <span className="text-[var(--muted-foreground)]">
              {t("quickSetup.activeCard.extraCapabilities")}
            </span>
            {SYNCABLE_EXTRA_SERVICES.map((item) => {
              const enabled = hasActiveService(catalog.services, item.service);
              const canOneClick =
                !enabled &&
                activeConnection &&
                activeProviderSyncable.includes(item.service);
              return (
                <span
                  key={item.service}
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${
                    enabled
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                  }`}
                >
                  {enabled && <Check size={12} />}
                  {t(item.titleKey)}
                  {canOneClick && activeConnection && (
                    <button
                      type="button"
                      disabled={syncingExtras || !catalogEditable}
                      onClick={() =>
                        void handleSyncExtraServices(
                          activeConnection.provider,
                          activeConnection.id,
                          activeConnection.name,
                          [item.service],
                        )
                      }
                      className="ml-1 rounded bg-[var(--primary)]/15 px-1.5 py-0.5 text-[11px] font-medium text-[var(--primary)] hover:bg-[var(--primary)]/25"
                    >
                      {t("quickSetup.action.enableNow")}
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        </section>
      )}

      {setupResult && (
        <section className="rounded-2xl border border-emerald-500/30 bg-emerald-500/[0.04] p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={20} />
              </div>
              <div>
                <h3 className="text-base font-semibold text-[var(--foreground)]">
                  {t("quickSetup.success.title")}
                </h3>
                <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                  {t("quickSetup.success.subtitle", {
                    provider: setupResult.providerLabel,
                    model: setupResult.modelName,
                  })}
                </p>

                {setupResult.discoveredModels.length > 1 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
                    <span className="text-[var(--muted-foreground)]">
                      {t("quickSetup.success.switchDiscovered", {
                        count: setupResult.discoveredModels.length,
                      })}
                    </span>
                    <select
                      value={setupResult.modelName}
                      disabled={submitting}
                      onChange={(e) =>
                        void handleSwitchModelAfterSetup(e.target.value)
                      }
                      className={`${selectClass} w-auto max-w-xs py-1 text-[12px]`}
                    >
                      {setupResult.discoveredModels.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>

            <Link
              href="/chat"
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-semibold text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90"
            >
              {t("quickSetup.action.startChatNow")}
              <ArrowRight size={15} />
            </Link>
          </div>

          {(() => {
            const target = targetByProvider.get(setupResult.providerId);
            const candidates = SYNCABLE_EXTRA_SERVICES.filter(
              (item) =>
                Boolean(target?.services[item.service]) &&
                !hasActiveService(catalog.services, item.service),
            );
            if (candidates.length === 0 && syncedServices.length === 0) return null;

            return (
              <div className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-[var(--foreground)]">
                  <Zap size={15} className="text-amber-500" />
                  {t("quickSetup.sync.heading")}
                </div>

                {candidates.length > 0 && (
                  <div className="mt-3 space-y-2.5">
                    {candidates.map((item) => {
                      const svcSpec = target?.services[item.service];
                      const checked = selectedSyncServices.includes(item.service);
                      return (
                        <label
                          key={item.service}
                          className="flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--border)]/70 p-3 transition-colors hover:bg-[var(--accent)]/40"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              setSelectedSyncServices((prev) =>
                                e.target.checked
                                  ? [...prev, item.service]
                                  : prev.filter((s) => s !== item.service),
                              );
                            }}
                            className="mt-0.5 h-4 w-4 rounded accent-[var(--primary)]"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                              <span>{t(item.titleKey)}</span>
                              {svcSpec?.default_model && (
                                <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--muted-foreground)]">
                                  {svcSpec.default_model}
                                </span>
                              )}
                            </div>
                            <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">
                              {t(item.descKey)}
                            </p>
                          </div>
                        </label>
                      );
                    })}

                    <div className="pt-1">
                      <button
                        type="button"
                        disabled={
                          syncingExtras || selectedSyncServices.length === 0
                        }
                        onClick={() =>
                          void handleSyncExtraServices(
                            setupResult.providerId,
                            setupResult.connectionId,
                            setupResult.providerLabel,
                            selectedSyncServices,
                          )
                        }
                        className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
                      >
                        {syncingExtras && (
                          <Loader2 size={14} className="animate-spin" />
                        )}
                        {t("quickSetup.sync.submit")}
                      </button>
                    </div>
                  </div>
                )}

                {syncedServices.length > 0 && (
                  <p className="mt-3 flex items-center gap-1.5 text-[12px] font-medium text-emerald-700 dark:text-emerald-400">
                    <CheckCircle2 size={14} />
                    {t("quickSetup.sync.done", {
                      items: syncedServices
                        .map((s) => {
                          const found = SYNCABLE_EXTRA_SERVICES.find(
                            (x) => x.service === s,
                          );
                          return found ? t(found.titleKey) : s;
                        })
                        .join(", "),
                    })}
                  </p>
                )}
              </div>
            );
          })()}
        </section>
      )}

      {(showAddForm || !hasConfiguredLlm) && !setupResult && (
        <div className="space-y-6">
          <section className="space-y-3">
            <div>
              <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
                {t("quickSetup.step1.title")}
              </h2>
              <p className="mt-0.5 text-[13px] text-[var(--muted-foreground)]">
                {t("quickSetup.step1.subtitle")}
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURED_DOMESTIC_PROVIDERS.map(renderProviderCard)}
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowMoreVendors((prev) => !prev)}
                className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                {showMoreVendors ? (
                  <ChevronUp size={15} />
                ) : (
                  <ChevronDown size={15} />
                )}
                {t("quickSetup.step1.moreProviders")}
              </button>

              {showMoreVendors && (
                <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {MORE_PROVIDERS.map(renderProviderCard)}
                </div>
              )}
            </div>
          </section>

          <form
            onSubmit={handleQuickConnect}
            className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <ProviderIcon provider={selectedPreset.id} size={20} />
                <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
                  {t("quickSetup.step2.title", {
                    provider: t(selectedPreset.nameKey),
                  })}
                </h2>
              </div>

              {selectedPreset.keyUrl && (
                <a
                  href={selectedPreset.keyUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--primary)] hover:underline"
                >
                  {t("quickSetup.step2.getKeyLink")}
                  <ExternalLink size={13} />
                </a>
              )}
            </div>

            <div className="mt-4 space-y-4">
              {selectedPreset.requiresBaseUrl && (
                <label className="block space-y-1.5">
                  <span className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("quickSetup.step2.baseUrlLabel")}
                  </span>
                  <input
                    type="url"
                    required
                    value={customBaseUrl}
                    onChange={(e) => setCustomBaseUrl(e.target.value)}
                    placeholder="https://api.example.com/v1"
                    className={inputClass}
                  />
                </label>
              )}

              <label className="block space-y-1.5">
                <span className="text-[13px] font-medium text-[var(--foreground)]">
                  {t("API Key")}
                </span>
                <div className="relative">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={
                      selectedPreset.keyPlaceholderKey
                        ? t(selectedPreset.keyPlaceholderKey)
                        : "sk-..."
                    }
                    autoComplete="off"
                    className={`${inputClass} pr-10 font-mono text-[13px]`}
                  />
                  <button
                    type="button"
                    aria-label={
                      showApiKey
                        ? t("Hide")
                        : t("quickSetup.action.showKey")
                    }
                    onClick={() => setShowApiKey((prev) => !prev)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  >
                    {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </label>

              <div>
                {!selectedPreset.requiresManualModel ? (
                  <button
                    type="button"
                    onClick={() => setShowModelPicker((prev) => !prev)}
                    className="inline-flex items-center gap-1 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  >
                    {showModelPicker ? (
                      <ChevronUp size={13} />
                    ) : (
                      <ChevronDown size={13} />
                    )}
                    {t("quickSetup.step2.modelOverrideToggle", {
                      model:
                        manualModel ||
                        selectedPreset.recommendedModels[0] ||
                        t("Auto"),
                    })}
                  </button>
                ) : null}

                {(showModelPicker || selectedPreset.requiresManualModel) && (
                  <div className="mt-2 space-y-1.5">
                    <span className="block text-[12px] font-medium text-[var(--muted-foreground)]">
                      {t("quickSetup.step2.modelIdLabel")}
                    </span>
                    <input
                      type="text"
                      value={manualModel}
                      onChange={(e) => setManualModel(e.target.value)}
                      placeholder={
                        selectedPreset.recommendedModels[0] || "gpt-4o-mini"
                      }
                      className={`${inputClass} font-mono text-[13px]`}
                    />
                  </div>
                )}
              </div>

              {errorState && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/[0.06] p-3.5 text-[13px]">
                  <div className="flex items-start gap-2.5">
                    <AlertCircle
                      size={16}
                      className="mt-0.5 shrink-0 text-red-600 dark:text-red-400"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-red-700 dark:text-red-300">
                        {t(errorState.titleKey)}
                      </p>
                      <p className="mt-0.5 text-[12px] leading-relaxed text-red-700/90 dark:text-red-300/90">
                        {t(errorState.detailKey)}
                      </p>
                      {errorState.raw && (
                        <div className="mt-2">
                          <button
                            type="button"
                            onClick={() => setShowRawError((prev) => !prev)}
                            className="text-[11px] underline opacity-80 hover:opacity-100"
                          >
                            {showRawError
                              ? t("quickSetup.error.hideRaw")
                              : t("quickSetup.error.showRaw")}
                          </button>
                          {showRawError && (
                            <pre className="mt-1.5 max-h-28 overflow-auto rounded bg-black/5 p-2 font-mono text-[11px] whitespace-pre-wrap dark:bg-white/5">
                              {errorState.raw}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <button
                  type="submit"
                  disabled={submitting || !catalogEditable}
                  className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-[14px] font-semibold text-[var(--primary-foreground)] shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      {t("quickSetup.action.verifying")}
                    </>
                  ) : (
                    <>
                      <Zap size={15} />
                      {t("quickSetup.action.verifyAndEnable")}
                    </>
                  )}
                </button>

                <div className="flex items-center gap-3 text-[12px] text-[var(--muted-foreground)]">
                  {selectedTarget &&
                    getSyncableCapabilities(selectedPreset.id).length > 0 && (
                      <span>{t("quickSetup.step2.extraHint")}</span>
                    )}
                  <Link
                    href="/settings/connections"
                    className="inline-flex items-center gap-1 hover:text-[var(--foreground)] hover:underline"
                  >
                    <SlidersHorizontal size={12} />
                    {t("quickSetup.step2.advancedLink")}
                  </Link>
                </div>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
