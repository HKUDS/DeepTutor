"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { invalidateLLMOptionsCache } from "@/lib/llm-options";
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
  SYNCABLE_EXTRA_SERVICES,
  findQuickPreset,
  formatFriendlySetupError,
  getQuickProviderGroups,
  pickRecommendedModel,
  resolveQuickPresetRegion,
  type FriendlyErrorResult,
  type QuickProviderPreset,
} from "@/lib/quick-setup-presets";
import { inputClass, subPanelClass } from "./shared";

type SetupResultState = {
  providerId: string;
  providerLabel: string;
  connectionId: string;
  connection: CatalogConnection;
  modelName: string;
  discoveredModels: string[];
  profileId: string;
  modelEntryId: string;
  probeSkipped?: boolean;
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

const compactSelectClass =
  "h-9 max-w-[230px] cursor-pointer rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 pr-8 text-[13px] leading-5 text-[var(--foreground)] outline-none transition-[border-color,box-shadow] duration-150 hover:border-[color-mix(in_srgb,var(--foreground)_25%,var(--border))] focus:border-[var(--ring)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--ring)_16%,transparent)] disabled:cursor-not-allowed disabled:opacity-60";

export function QuickModelSetupWorkspace() {
  const { t, i18n } = useTranslation();
  const uiLanguage = i18n?.resolvedLanguage ?? i18n?.language ?? "zh";
  const { featured: featuredProviders, more: moreProviders } = useMemo(
    () => getQuickProviderGroups(uiLanguage),
    [uiLanguage],
  );

  const {
    catalog,
    connectionTargets,
    providers,
    catalogEditable,
    settingsLoading,
    reloadSettings,
    saveRegistry,
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
  const hasConfiguredEmbedding = useMemo(
    () => hasActiveService(catalog.services, "embedding"),
    [catalog.services],
  );
  const hasConfiguredSearch = useMemo(
    () => hasActiveService(catalog.services, "search"),
    [catalog.services],
  );
  const hasConfiguredVoice = useMemo(
    () =>
      hasActiveService(catalog.services, "tts") ||
      hasActiveService(catalog.services, "stt"),
    [catalog.services],
  );
  const hasConfiguredMultimodal = useMemo(
    () =>
      hasActiveService(catalog.services, "imagegen") ||
      hasActiveService(catalog.services, "videogen"),
    [catalog.services],
  );

  const [showAddForm, setShowAddForm] = useState(false);
  const initializedShowFormRef = useRef(false);
  useEffect(() => {
    if (settingsLoading || initializedShowFormRef.current) return;
    initializedShowFormRef.current = true;
    setShowAddForm(!hasConfiguredLlm);
  }, [settingsLoading, hasConfiguredLlm]);

  const [selectedVendorId, setSelectedVendorId] = useState<string>(
    () => featuredProviders[0]?.id ?? "deepseek",
  );
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
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
    findQuickPreset(selectedVendorId) ?? featuredProviders[0];

  const activeRegion = useMemo(
    () => resolveQuickPresetRegion(selectedPreset, selectedRegionId, uiLanguage),
    [selectedPreset, selectedRegionId, uiLanguage],
  );
  const activeKeyUrl = activeRegion?.keyUrl ?? selectedPreset.keyUrl;

  const selectedTarget = targetByProvider.get(selectedPreset.id);

  const resolveDefaultBaseUrl = (vendorId: string): string => {
    if (vendorId === "custom") return customBaseUrl.trim();
    if (vendorId === selectedPreset.id && activeRegion?.baseUrl) {
      return activeRegion.baseUrl;
    }
    const targetUrl = targetByProvider.get(vendorId)?.default_base_url;
    if (targetUrl) return targetUrl;
    const llmOpt = providers.llm?.find((p) => p.value === vendorId);
    return llmOpt?.base_url ?? "";
  };

  const getSyncableCapabilities = useCallback(
    (vendorId: string): ServiceName[] => {
      const target = targetByProvider.get(vendorId);
      if (!target) return [];
      return SYNCABLE_EXTRA_SERVICES.map((item) => item.service).filter((svc) =>
        Boolean(target.services[svc]),
      );
    },
    [targetByProvider],
  );

  const handleSelectVendor = (vendorId: string) => {
    setSelectedVendorId(vendorId);
    setSelectedRegionId(null);
    setErrorState(null);
    setShowRawError(false);
    setSetupResult(null);
    setSyncedServices([]);
    setManualModel("");
    setShowModelPicker(false);
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

      const probeAccepted =
        probeRes.ok &&
        (probePayload.status === "connected" ||
          probePayload.status === "unavailable");

      if (!probeAccepted) {
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

      const probeSkipped = probePayload.status === "unavailable";
      const discoveredIds = probeSkipped
        ? []
        : (probePayload.models ?? [])
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

      invalidateLLMOptionsCache();

      if (!catalog.services.task?.mode || catalog.services.task.mode === "profiles") {
        const hasExplicitTask = hasActiveService(catalog.services, "task");
        if (!hasExplicitTask) {
          await saveRegistry({
            kind: "task_choice",
            task: { mode: "inherit" },
          });
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
        probeSkipped,
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
    connectionBaseUrl?: string,
  ) => {
    if (!servicesToSync.length || syncingExtras) return;
    const target = targetByProvider.get(targetProviderId);
    if (!target) return;

    setSyncingExtras(true);
    setErrorState(null);
    const newlySynced: ServiceName[] = [];
    let firstFailure: string | null = null;
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

        const resolvedBaseUrl =
          connectionBaseUrl &&
          (!svcSpec.base_url || svcSpec.base_url === target.default_base_url)
            ? connectionBaseUrl
            : svcSpec.base_url || target.default_base_url || "";

        const profile: CatalogProfile = {
          id: profileId,
          name: connectionName,
          binding: svcSpec.provider || targetProviderId,
          connection_id: connectionId,
          base_url: resolvedBaseUrl,
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
        } else {
          const payload = await res.json().catch(() => ({}));
          if (!firstFailure) {
            firstFailure =
              typeof payload.detail === "string"
                ? payload.detail
                : `HTTP ${res.status}`;
          }
        }
      }
      if (newlySynced.length > 0) {
        invalidateLLMOptionsCache();
        setSyncedServices((prev) => [...new Set([...prev, ...newlySynced])]);
        setSelectedSyncServices((prev) =>
          prev.filter((item) => !newlySynced.includes(item)),
        );
        await reloadSettings();
      }
      if (firstFailure) {
        setErrorState(formatFriendlySetupError(null, firstFailure));
      }
    } finally {
      setSyncingExtras(false);
    }
  };

  const handleSwitchActiveLlm = async (value: string) => {
    const [profileId, modelId] = value.split("::");
    if (!profileId || !modelId) return;
    setSwitchingActive(true);
    setErrorState(null);
    try {
      const ok = await saveRegistry({
        kind: "default",
        service: "llm",
        profile_id: profileId,
        model_id: modelId,
      });
      if (!ok) {
        setErrorState(formatFriendlySetupError(null));
      }
    } finally {
      setSwitchingActive(false);
    }
  };

  const handleSwitchModelAfterSetup = async (nextModelName: string) => {
    if (!setupResult || !nextModelName.trim()) return;
    setSubmitting(true);
    setErrorState(null);
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
        invalidateLLMOptionsCache();
        setSetupResult((prev) =>
          prev ? { ...prev, modelName: nextModelName.trim() } : null,
        );
        await reloadSettings();
      } else {
        const payload = await res.json().catch(() => ({}));
        setErrorState(
          formatFriendlySetupError(
            null,
            typeof payload.detail === "string"
              ? payload.detail
              : `HTTP ${res.status}`,
          ),
        );
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
  }, [activeConnection, catalog.services, getSyncableCapabilities]);

  const renderProviderCard = (preset: QuickProviderPreset) => {
    const isSelected = selectedPreset.id === preset.id;
    const syncable = getSyncableCapabilities(preset.id);
    const hasEmbedding = syncable.includes("embedding");
    const hasVoice = syncable.includes("tts") || syncable.includes("stt");
    const extraTags = [
      hasEmbedding ? t("quickSetup.tag.knowledgeBase") : null,
      hasVoice ? t("quickSetup.tag.voice") : null,
    ].filter(Boolean);

    return (
      <button
        key={preset.id}
        type="button"
        onClick={() => handleSelectVendor(preset.id)}
        className={`group relative flex flex-col gap-2 rounded-xl border p-4 text-left transition-[border-color,background-color,box-shadow] duration-150 ${
          isSelected
            ? "border-[var(--foreground)] bg-[color-mix(in_srgb,var(--foreground)_3%,var(--background))] shadow-sm ring-1 ring-[var(--foreground)]"
            : "border-[color-mix(in_srgb,var(--border)_85%,transparent)] bg-[var(--background)] hover:border-[color-mix(in_srgb,var(--foreground)_28%,var(--border))] hover:bg-[color-mix(in_srgb,var(--muted)_35%,transparent)]"
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--muted)_80%,transparent)]">
              <ProviderIcon provider={preset.id} size={18} />
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="truncate text-[14px] font-semibold leading-5 text-[var(--foreground)]">
                {t(preset.nameKey)}
              </span>
              {preset.badgeKey && (
                <span className="shrink-0 rounded-md bg-[color-mix(in_srgb,var(--muted)_95%,transparent)] px-1.5 py-0.5 text-[11px] font-medium leading-4 text-[var(--muted-foreground)]">
                  {t(preset.badgeKey)}
                </span>
              )}
            </div>
          </div>
          <span
            className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
              isSelected
                ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
                : "border-[var(--border)] bg-transparent"
            }`}
          >
            {isSelected && <Check size={10} strokeWidth={3} />}
          </span>
        </div>

        <p className="text-[12.5px] leading-[1.55] text-[var(--muted-foreground)]">
          {t(preset.taglineKey)}
        </p>

        {extraTags.length > 0 && (
          <p className="text-[11.5px] leading-4 text-[color-mix(in_srgb,var(--muted-foreground)_85%,transparent)]">
            {extraTags.join(" · ")}
          </p>
        )}
      </button>
    );
  };

  if (catalogEditable === false) {
    return (
      <div className={`space-y-3 p-5 ${subPanelClass}`}>
        <p className="text-[13.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t("Only administrators can manage providers.")}
        </p>
        <Link
          href="/chat"
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90"
        >
          {t("quickSetup.action.startChat")}
          <ArrowRight size={14} />
        </Link>
      </div>
    );
  }

  const formVisible = !settingsLoading && (showAddForm || !hasConfiguredLlm) && !setupResult;

  return (
    <div className="space-y-8">
      {errorState && !formVisible && (
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
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-red-700/90 dark:text-red-300/90">
                {t(errorState.detailKey)}
              </p>
            </div>
          </div>
        </div>
      )}
      {/* Compact 3-Step Configuration Progress Strip */}
      <section className={`overflow-hidden ${subPanelClass}`}>
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[color-mix(in_srgb,var(--border)_65%,transparent)] px-5 py-3">
          <h2 className="text-[13px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("quickSetup.progress.title")}
          </h2>
          <span className="text-[12px] text-[var(--muted-foreground)]">
            {t("quickSetup.progress.scopeHint")}
          </span>
        </div>

        <div className="grid grid-cols-1 divide-y divide-[color-mix(in_srgb,var(--border)_65%,transparent)] md:grid-cols-3 md:divide-x md:divide-y-0">
          {/* Step 1: Chat LLM */}
          <div className="px-5 py-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    hasConfiguredLlm ? "bg-emerald-500" : "bg-[var(--foreground)]"
                  }`}
                />
                <span className="text-[13px] font-medium text-[var(--foreground)]">
                  {t("quickSetup.progress.step1Title")}
                </span>
              </div>
              <span
                className={`text-[11.5px] font-medium ${
                  hasConfiguredLlm
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-[var(--foreground)]"
                }`}
              >
                {hasConfiguredLlm
                  ? t("quickSetup.progress.done")
                  : t("quickSetup.progress.required")}
              </span>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-[1.55] text-[var(--muted-foreground)]">
              {t("quickSetup.progress.step1Desc")}
            </p>
          </div>

          {/* Step 2: Embedding */}
          <div className="px-5 py-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    hasConfiguredEmbedding ? "bg-emerald-500" : "bg-[var(--border)]"
                  }`}
                />
                <span className="text-[13px] font-medium text-[var(--foreground)]">
                  {t("quickSetup.progress.step2Title")}
                </span>
              </div>
              <span
                className={`text-[11.5px] font-medium ${
                  hasConfiguredEmbedding
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {hasConfiguredEmbedding
                  ? t("quickSetup.progress.done")
                  : t("quickSetup.progress.recommended")}
              </span>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-[1.55] text-[var(--muted-foreground)]">
              {t("quickSetup.progress.step2Desc")}
            </p>
            {!hasConfiguredEmbedding && (
              <Link
                href="/settings/embedding"
                className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-[var(--foreground)] underline decoration-[var(--border)] underline-offset-4 hover:decoration-[var(--foreground)]"
              >
                {t("quickSetup.progress.configureEmbedding")}
                <ArrowRight size={12} />
              </Link>
            )}
          </div>

          {/* Step 3: Task model & optional services */}
          <div className="px-5 py-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    hasConfiguredSearch ||
                    hasConfiguredVoice ||
                    hasConfiguredMultimodal
                      ? "bg-emerald-500"
                      : "bg-[var(--border)]"
                  }`}
                />
                <span className="text-[13px] font-medium text-[var(--foreground)]">
                  {t("quickSetup.progress.step3Title")}
                </span>
              </div>
              <span className="text-[11.5px] text-[var(--muted-foreground)]">
                {t("quickSetup.progress.optional")}
              </span>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-[1.55] text-[var(--muted-foreground)]">
              {t("quickSetup.progress.step3Desc")}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
              <Link
                href="/settings/task-models"
                className="text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)]"
              >
                {t("Task models")}
              </Link>
              <Link
                href="/settings/search"
                className="text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)]"
              >
                {t("Search")}
              </Link>
              <Link
                href="/settings/voice"
                className="text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)]"
              >
                {t("settings.nav.voice")}
              </Link>
              <Link
                href="/settings/multimodal"
                className="text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)]"
              >
                {t("Multimodal generation")}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Active Model Bar */}
      {hasConfiguredLlm && activeLlm && (
        <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-5 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--muted)_80%,transparent)]">
                <ProviderIcon
                  provider={activeLlm.profile.binding || "openai"}
                  size={20}
                />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
                  <span>{t("quickSetup.activeCard.label")}</span>
                  <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {t("quickSetup.activeCard.ready")}
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
                  <span className="truncate text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
                    {activeLlm.model?.user_name ||
                      activeLlm.model?.name ||
                      activeLlm.model?.model}
                  </span>
                  <span className="truncate text-[12.5px] text-[var(--muted-foreground)]">
                    {activeLlm.profile.name}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {llmRows.length > 1 && (
                <select
                  aria-label={t("quickSetup.activeCard.switchLabel")}
                  disabled={switchingActive || !catalogEditable}
                  value={`${activeLlm.profile.id}::${activeLlm.model?.id ?? ""}`}
                  onChange={(e) => void handleSwitchActiveLlm(e.target.value)}
                  className={compactSelectClass}
                >
                  {llmRows.map((row) => (
                    <option
                      key={`${row.profile.id}::${row.model?.id ?? ""}`}
                      value={`${row.profile.id}::${row.model?.id ?? ""}`}
                    >
                      {row.model?.user_name ||
                        row.model?.name ||
                        row.model?.model}{" "}
                      · {row.profile.name}
                    </option>
                  ))}
                </select>
              )}

              <Link
                href="/chat"
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90"
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
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
              >
                <Plus size={14} />
                {showAddForm
                  ? t("quickSetup.action.hideForm")
                  : t("quickSetup.action.addModel")}
              </button>
            </div>
          </div>

          <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-[color-mix(in_srgb,var(--border)_65%,transparent)] pt-3 text-[12px] text-[var(--muted-foreground)]">
            <span>{t("quickSetup.activeCard.extraCapabilities")}</span>
            {SYNCABLE_EXTRA_SERVICES.map((item) => {
              const enabled = hasActiveService(catalog.services, item.service);
              const canOneClick =
                !enabled &&
                activeConnection &&
                activeProviderSyncable.includes(item.service);
              return (
                <span
                  key={item.service}
                  className={`inline-flex items-center gap-1.5 ${
                    enabled ? "text-[var(--foreground)]" : ""
                  }`}
                >
                  {enabled ? (
                    <Check
                      size={13}
                      strokeWidth={2.2}
                      className="text-emerald-600 dark:text-emerald-400"
                    />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--border)]" />
                  )}
                  <span>{t(item.titleKey)}</span>
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
                          activeConnection.base_url,
                        )
                      }
                      className="ml-0.5 font-medium text-[var(--foreground)] underline underline-offset-4 hover:opacity-80"
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

      {/* Post-Setup Success Card + One-Key Multi-Service Sync */}
      {setupResult && (
        <section className="rounded-xl border border-emerald-500/35 bg-[color-mix(in_srgb,#10b981_5%,var(--background))] p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={18} />
              </div>
              <div>
                <h3 className="text-[15px] font-semibold text-[var(--foreground)]">
                  {t("quickSetup.success.title")}
                </h3>
                <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                  {t("quickSetup.success.subtitle", {
                    provider: setupResult.providerLabel,
                    model: setupResult.modelName,
                  })}
                </p>

                {setupResult.probeSkipped && (
                  <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                    {t("quickSetup.success.probeSkipped")}
                  </p>
                )}

                {setupResult.discoveredModels.length > 1 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
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
                      className={compactSelectClass}
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
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-4 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90"
            >
              {t("quickSetup.action.startChatNow")}
              <ArrowRight size={14} />
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
              <div className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-[var(--foreground)]">
                  <Zap size={14} strokeWidth={2} />
                  {t("quickSetup.sync.heading")}
                </div>

                {candidates.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {candidates.map((item) => {
                      const svcSpec = target?.services[item.service];
                      const checked = selectedSyncServices.includes(item.service);
                      return (
                        <label
                          key={item.service}
                          className="flex cursor-pointer items-start gap-3 rounded-lg border border-[color-mix(in_srgb,var(--border)_75%,transparent)] p-3 transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_35%,transparent)]"
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
                            className="mt-0.5 h-4 w-4 rounded accent-[var(--foreground)]"
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
                            <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                              {t(item.descKey)}
                            </p>
                          </div>
                        </label>
                      );
                    })}

                    <div className="pt-1.5">
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
                            setupResult.connection.base_url,
                          )
                        }
                        className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
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
                  <p className="mt-3 flex items-center gap-1.5 text-[12.5px] font-medium text-emerald-600 dark:text-emerald-400">
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

      {/* Main 1-Screen Quick Setup Flow */}
      {!settingsLoading && (showAddForm || !hasConfiguredLlm) && !setupResult && (
        <div className="space-y-7">
          {/* Step 1: Pick a Provider */}
          <section className="space-y-3.5">
            <div>
              <h2 className="text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                {t("quickSetup.step1.title")}
              </h2>
              <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                {t("quickSetup.step1.subtitle")}
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {featuredProviders.map(renderProviderCard)}
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowMoreVendors((prev) => !prev)}
                className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                {showMoreVendors ? (
                  <ChevronUp size={14} />
                ) : (
                  <ChevronDown size={14} />
                )}
                {t("quickSetup.step1.moreProviders")}
              </button>

              {showMoreVendors && (
                <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {moreProviders.map(renderProviderCard)}
                </div>
              )}
            </div>
          </section>

          {/* Step 2: API Key & One-Click Connect */}
          <form onSubmit={handleQuickConnect} className={`p-5 sm:p-6 ${subPanelClass}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <ProviderIcon provider={selectedPreset.id} size={18} />
                <h2 className="text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                  {t("quickSetup.step2.title", {
                    provider: t(selectedPreset.nameKey),
                  })}
                </h2>
              </div>

              {activeKeyUrl && (
                <a
                  href={activeKeyUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[12.5px] font-medium text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)]"
                >
                  {t("quickSetup.step2.getKeyLink")}
                  <ExternalLink size={12} />
                </a>
              )}
            </div>

            <div className="mt-4 space-y-4">
              {selectedPreset.regions && selectedPreset.regions.length > 0 && (
                <div className="space-y-1.5">
                  <span className="block text-[13px] font-medium text-[var(--foreground)]">
                    {t("quickSetup.step2.regionLabel")}
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {selectedPreset.regions.map((region) => {
                      const isActive = activeRegion?.id === region.id;
                      return (
                        <button
                          key={region.id}
                          type="button"
                          aria-pressed={isActive}
                          onClick={() => setSelectedRegionId(region.id)}
                          className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                            isActive
                              ? "border-[var(--foreground)] bg-[color-mix(in_srgb,var(--foreground)_5%,var(--background))] text-[var(--foreground)]"
                              : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                          }`}
                        >
                          {t(region.labelKey)}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[12px] text-[var(--muted-foreground)]">
                    {t("quickSetup.step2.regionHint")}
                  </p>
                </div>
              )}
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
                    className={`${inputClass} bg-[var(--background)]`}
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
                    className={`${inputClass} bg-[var(--background)] pr-10 font-mono text-[13px]`}
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
                    className="inline-flex items-center gap-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
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
                      className={`${inputClass} bg-[var(--background)] font-mono text-[13px]`}
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
                      <p className="mt-0.5 text-[12.5px] leading-relaxed text-red-700/90 dark:text-red-300/90">
                        {t(errorState.detailKey)}
                      </p>
                      {errorState.raw && (
                        <div className="mt-2">
                          <button
                            type="button"
                            onClick={() => setShowRawError((prev) => !prev)}
                            className="text-[11.5px] underline opacity-80 hover:opacity-100"
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
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-[var(--foreground)] px-5 text-[13.5px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <Loader2 size={15} className="animate-spin" />
                      {t("quickSetup.action.verifying")}
                    </>
                  ) : (
                    <>
                      <Zap size={14} strokeWidth={2} />
                      {t("quickSetup.action.verifyAndEnable")}
                    </>
                  )}
                </button>

                <div className="flex flex-wrap items-center gap-4 text-[12px] text-[var(--muted-foreground)]">
                  {selectedTarget &&
                    getSyncableCapabilities(selectedPreset.id).length > 0 && (
                      <span>{t("quickSetup.step2.extraHint")}</span>
                    )}
                  <Link
                    href="/settings/connections"
                    className="inline-flex items-center gap-1 transition-colors hover:text-[var(--foreground)] hover:underline"
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
