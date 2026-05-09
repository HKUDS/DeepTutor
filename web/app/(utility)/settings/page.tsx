/* eslint-disable i18n/no-literal-ui-text */
"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Eye,
  EyeOff,
  Info,
  Loader2,
  Plus,
  Rocket,
  Save,
  Search,
  Terminal,
  Trash2,
  Wand2,
} from "lucide-react";

import { useTranslation } from "react-i18next";

import { writeStoredLanguage } from "@/context/app-shell-storage";
import { ModelAccessSummary } from "@/features/multi-user/components/ModelAccessSummary";
import type { ModelAccess } from "@/features/multi-user/types";
import { apiFetch, apiUrl } from "@/lib/api";
import { setTheme as applyThemePreference } from "@/lib/theme";

type ServiceName = "llm" | "embedding" | "search";

type CatalogModel = {
  id: string;
  name: string;
  model: string;
  dimension?: string;
  send_dimensions?: boolean;
  // CSV of dims supported natively by the current model — refreshed by the
  // backend on every successful "Run test" for an embedding service.
  supported_dimensions?: string;
  context_window?: string;
  context_window_source?: string;
  context_window_detected_at?: string;
};

type CatalogProfile = {
  id: string;
  name: string;
  binding?: string;
  provider?: string;
  base_url: string;
  api_key: string;
  api_version: string;
  extra_headers?: Record<string, string> | string;
  proxy?: string;
  max_results?: number;
  models: CatalogModel[];
};

type CatalogService = {
  active_profile_id: string | null;
  active_model_id?: string | null;
  profiles: CatalogProfile[];
};

type Catalog = {
  version: number;
  services: {
    llm: CatalogService;
    embedding: CatalogService;
    search: CatalogService;
  };
};

type UiSettings = {
  theme: "light" | "dark" | "glass" | "snow";
  language: "en" | "zh";
};

type ProviderOption = {
  value: string;
  label: string;
  base_url?: string;
  default_dim?: string;
};

type SettingsPayload = {
  ui: UiSettings;
  catalog?: Catalog;
  model_access?: ModelAccess;
  providers?: Record<ServiceName, ProviderOption[]>;
};

type SystemStatus = {
  backend: { status: string; timestamp: string };
  llm: { status: string; model?: string; error?: string };
  embeddings: { status: string; model?: string; error?: string };
  search: { status: string; provider?: string; error?: string };
};

const SERVICES = ["llm", "embedding", "search"] as const;

// ---------------------------------------------------------------------------

function cloneCatalog(catalog: Catalog): Catalog {
  return JSON.parse(JSON.stringify(catalog)) as Catalog;
}

function getActiveProfile(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogProfile | null {
  const service = catalog.services[serviceName];
  return (
    service.profiles.find(
      (profile) => profile.id === service.active_profile_id,
    ) ??
    service.profiles[0] ??
    null
  );
}

function getActiveModel(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogModel | null {
  if (serviceName === "search") return null;
  const service = catalog.services[serviceName];
  const profile = getActiveProfile(catalog, serviceName);
  if (!profile) return null;
  return (
    profile.models.find((model) => model.id === service.active_model_id) ??
    profile.models[0] ??
    null
  );
}

function serviceIcon(service: ServiceName) {
  if (service === "llm") return <Brain className="h-3.5 w-3.5" />;
  if (service === "embedding") return <Database className="h-3.5 w-3.5" />;
  return <Search className="h-3.5 w-3.5" />;
}

function serviceLabel(
  service: ServiceName,
  t: (key: string) => string,
): string {
  if (service === "llm") return t("LLM");
  if (service === "embedding") return t("Embedding");
  return t("Search");
}

function activeProfileDetail(
  profile: CatalogProfile | null,
  service: ServiceName,
  t: (key: string) => string,
): string {
  if (!profile) return t("No profile");
  if (service === "search") return profile.provider || t("No provider");
  return profile.base_url || t("No endpoint");
}

function activeModelDetail(
  profile: CatalogProfile | null,
  model: CatalogModel | null,
  service: ServiceName,
  t: (key: string) => string,
): string {
  if (service === "search") return profile?.provider || t("No provider");
  return model?.model || model?.name || t("No model selected");
}

function servicePendingApply(
  catalog: Catalog,
  draft: Catalog,
  service: ServiceName,
): boolean {
  return (
    JSON.stringify(catalog.services[service]) !==
    JSON.stringify(draft.services[service])
  );
}

function statusDotClass(configured: boolean, hasError: boolean): string {
  if (hasError) return "bg-red-400";
  if (configured) return "bg-emerald-500";
  return "bg-[var(--border)]";
}

function defaultCatalog(): Catalog {
  return {
    version: 1,
    services: {
      llm: { active_profile_id: null, active_model_id: null, profiles: [] },
      embedding: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      search: { active_profile_id: null, profiles: [] },
    },
  };
}

const fieldControlClass =
  "w-full rounded-lg border border-[var(--border)] px-3 py-2 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]";

const inputClass = `${fieldControlClass} bg-transparent placeholder:text-[var(--muted-foreground)]/40`;

const nativeSelectClass = `${fieldControlClass} bg-[var(--background)] cursor-pointer disabled:cursor-not-allowed disabled:opacity-60`;

const selectClass = `${nativeSelectClass} appearance-none`;

const selectOptionClass = "bg-[var(--background)] text-[var(--foreground)]";

function stringifyExtraHeaders(value: CatalogProfile["extra_headers"]): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

function formatContextWindowSource(
  source: string | undefined,
  t: (key: string) => string,
): string {
  if (source === "manual") return t("Manual");
  if (source === "metadata") return t("Auto");
  if (source === "default") return t("Default");
  return t("Unset");
}

function formatContextWindowUpdatedAt(
  value: string | undefined,
  language: "en" | "zh",
): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// ---------------------------------------------------------------------------
// Tour onboarding steps
// ---------------------------------------------------------------------------

const TOUR_GUIDE_STEPS = [
  {
    target: "tour-llm",
    service: "llm" as const,
    titleKey: "settingsTour.llm.title",
    descKey: "settingsTour.llm.desc",
  },
  {
    target: "tour-embedding",
    service: "embedding" as const,
    titleKey: "settingsTour.embedding.title",
    descKey: "settingsTour.embedding.desc",
  },
  {
    target: "tour-search",
    service: "search" as const,
    titleKey: "settingsTour.search.title",
    descKey: "settingsTour.search.desc",
  },
  {
    target: "tour-save-test",
    titleKey: "settingsTour.saveTest.title",
    descKey: "settingsTour.saveTest.desc",
  },
  {
    target: "tour-actions",
    titleKey: "settingsTour.apply.title",
    descKey: "settingsTour.apply.desc",
  },
];

const supportedSearchProviders = [
  "brave",
  "tavily",
  "jina",
  "searxng",
  "duckduckgo",
  "perplexity",
] as const;
const deprecatedSearchProviders = new Set([
  "exa",
  "serper",
  "baidu",
  "openrouter",
]);

// ---------------------------------------------------------------------------
// Spotlight overlay component
// ---------------------------------------------------------------------------

function SpotlightOverlay({
  stepIndex,
  onNext,
  onSkip,
}: {
  stepIndex: number;
  onNext: () => void;
  onSkip: () => void;
}) {
  const { t } = useTranslation();
  const [rect, setRect] = useState<DOMRect | null>(null);
  const guideStep = TOUR_GUIDE_STEPS[stepIndex];

  useEffect(() => {
    if (!guideStep) return;
    const frame = window.requestAnimationFrame(() => {
      const el = document.querySelector(`[data-tour="${guideStep.target}"]`);
      setRect(el ? el.getBoundingClientRect() : null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [guideStep]);

  if (!guideStep || !rect) return null;

  const pad = 8;
  const holeLeft = rect.left - pad;
  const holeTop = rect.top - pad;
  const holeW = rect.width + pad * 2;
  const holeH = rect.height + pad * 2;

  const clipPath = `polygon(
    0% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%,
    ${holeLeft}px ${holeTop}px,
    ${holeLeft}px ${holeTop + holeH}px,
    ${holeLeft + holeW}px ${holeTop + holeH}px,
    ${holeLeft + holeW}px ${holeTop}px,
    ${holeLeft}px ${holeTop}px
  )`;

  const tooltipTop = holeTop + holeH + 12;
  const tooltipLeft = Math.max(16, Math.min(holeLeft, window.innerWidth - 340));

  return (
    <div className="fixed inset-0 z-[9999]">
      <div
        className="absolute inset-0 bg-black/50 transition-all duration-300"
        style={{ clipPath }}
      />
      <div
        className="absolute z-10 w-[320px] rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-2xl"
        style={{ top: tooltipTop, left: tooltipLeft }}
      >
        <div className="mb-1 text-[13px] font-semibold text-[var(--foreground)]">
          {t(guideStep.titleKey)}
        </div>
        <p className="mb-4 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
          {t(guideStep.descKey)}
        </p>
        <div className="flex items-center justify-between">
          <button
            onClick={onSkip}
            className="text-[12px] text-[var(--muted-foreground)]/60 transition-colors hover:text-[var(--muted-foreground)]"
          >
            {t("Skip tour")}
          </button>
          <button
            onClick={onNext}
            className="inline-flex items-center gap-1 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80"
          >
            {stepIndex < TOUR_GUIDE_STEPS.length - 1 ? t("Next") : t("Got it")}
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Embedding dimension field — dropdown when supported list is known, free
// input otherwise, with a "Detected: Xd · Use this" affordance after a test.
// ---------------------------------------------------------------------------

const CUSTOM_DIM_SENTINEL = "__custom__";
const AUTO_DIM_SENTINEL = "";

function parseSupportedCsv(csv: string | undefined): number[] {
  if (!csv) return [];
  return csv
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n) && n > 0);
}

type EmbeddingCapabilities = {
  detected_dim?: number;
  default_dim?: number;
  supported_dimensions?: number[];
  supports_variable_dimensions?: boolean;
  model_known?: boolean;
  active_dim?: number;
  active_dim_source?: string;
};

function sourceBadge(
  source: string | undefined,
  t: (key: string) => string,
): { label: string; tone: "muted" | "ok" | "warn" } | null {
  // The probe is the single source of truth: a successful test always emits
  // ``"detected"``. Other codes are legacy and no longer produced.
  if (source === "detected") {
    return { label: t("Source: detected from API probe"), tone: "ok" };
  }
  return null;
}

function DimensionField({
  activeModel,
  activeBinding,
  capabilities,
  embeddingDefaultDim,
  inputClass,
  onChangeDimension,
}: {
  activeModel: CatalogModel;
  activeBinding?: string;
  capabilities: EmbeddingCapabilities | null;
  embeddingDefaultDim: (binding?: string) => string;
  inputClass: string;
  onChangeDimension: (value: string) => void;
}) {
  const { t } = useTranslation();
  const fallback = embeddingDefaultDim(activeBinding);
  // Raw catalog state — empty string means "not yet configured / auto on
  // next test". We never substitute the fallback into the input value, only
  // into the placeholder, so the user can fully clear the field.
  const rawValue = activeModel.dimension ?? "";
  const isEmpty = rawValue === "";
  const currentNum = isEmpty ? NaN : Number(rawValue);

  // Live capabilities (from current run) override the cached CSV on disk.
  const liveSupported = capabilities?.supported_dimensions;
  const cachedSupported = parseSupportedCsv(activeModel.supported_dimensions);
  const supported =
    liveSupported && liveSupported.length > 0 ? liveSupported : cachedSupported;
  const supportsVariable =
    capabilities?.supports_variable_dimensions ?? supported.length > 1;

  const useDropdown = supported.length > 1 && supportsVariable;
  const currentInList =
    Number.isFinite(currentNum) && supported.includes(currentNum);
  // True when the user explicitly opted out of the dropdown by picking
  // "Custom…". Stays true until they click "Use a supported value" or pick
  // a real value from the dropdown again.
  const [customRequested, setCustomRequested] = useState<boolean>(false);
  // Force custom mode when the catalog has a non-empty value that isn't in
  // the list — that's a sign the user typed something custom and we should
  // respect it. Empty catalog stays in dropdown mode (showing "Auto").
  const customMode =
    customRequested || (useDropdown && !isEmpty && !currentInList);

  const detected = capabilities?.detected_dim;
  const showDetectedBadge =
    typeof detected === "number" &&
    detected > 0 &&
    detected !== currentNum &&
    !isEmpty;

  const sourceInfo = sourceBadge(capabilities?.active_dim_source, t);

  const disabled = activeModel.send_dimensions === false;

  const handleSelect = (value: string) => {
    if (value === CUSTOM_DIM_SENTINEL) {
      setCustomRequested(true);
      return;
    }
    setCustomRequested(false);
    // AUTO_DIM_SENTINEL is "" — clears the catalog, triggers auto-fill on
    // the next test. Real numeric values flow through unchanged.
    onChangeDimension(value);
  };

  const dropdownValue = isEmpty
    ? AUTO_DIM_SENTINEL
    : currentInList
      ? String(currentNum)
      : CUSTOM_DIM_SENTINEL;

  return (
    <div className="space-y-1.5">
      {useDropdown && !customMode ? (
        <select
          className={nativeSelectClass}
          value={dropdownValue}
          onChange={(e) => handleSelect(e.target.value)}
          disabled={disabled}
        >
          <option className={selectOptionClass} value={AUTO_DIM_SENTINEL}>
            {t("Auto (probe on next test)")}
          </option>
          {supported.map((dim) => (
            <option className={selectOptionClass} key={dim} value={String(dim)}>
              {dim}
            </option>
          ))}
          <option className={selectOptionClass} value={CUSTOM_DIM_SENTINEL}>
            {t("Custom…")}
          </option>
        </select>
      ) : (
        <input
          className={inputClass}
          value={rawValue}
          placeholder={fallback}
          onChange={(e) => onChangeDimension(e.target.value)}
          disabled={disabled}
          inputMode="numeric"
        />
      )}
      {useDropdown && customMode && (
        <button
          type="button"
          onClick={() => {
            setCustomRequested(false);
            if (isEmpty) {
              return;
            }
            // Snap to the closest supported value to keep the catalog honest.
            const closest = supported.reduce((acc, dim) =>
              Math.abs(dim - currentNum) < Math.abs(acc - currentNum)
                ? dim
                : acc,
            );
            onChangeDimension(String(closest));
          }}
          className="text-[11px] text-[var(--muted-foreground)] underline-offset-2 hover:underline"
        >
          {t("Use a supported value")}
        </button>
      )}
      {sourceInfo && (
        <div
          className={`text-[11px] ${
            sourceInfo.tone === "warn"
              ? "text-amber-600 dark:text-amber-400"
              : sourceInfo.tone === "ok"
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-[var(--muted-foreground)]"
          }`}
        >
          {sourceInfo.label}
        </div>
      )}
      {showDetectedBadge && (
        <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span>
            {t("Detected")}: <strong>{detected}d</strong>
          </span>
          <button
            type="button"
            onClick={() => onChangeDimension(String(detected))}
            className="rounded-md border border-[var(--border)]/60 px-1.5 py-0.5 text-[10px] text-[var(--foreground)] transition-colors hover:border-[var(--border)]"
            disabled={disabled}
          >
            {t("Use this")}
          </button>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Main component
// ═══════════════════════════════════════════════════════════════════════════

function SettingsPageContent() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | "glass" | "snow">(
    "light",
  );
  const [language, setLanguage] = useState<"en" | "zh">("en");
  const [catalog, setCatalog] = useState<Catalog>(defaultCatalog());
  const [draft, setDraft] = useState<Catalog>(defaultCatalog());
  const [modelAccess, setModelAccess] = useState<ModelAccess | null>(null);
  // ``null`` means "we haven't received a /settings response yet". We render
  // a loading skeleton while it's null so non-admin users never see an empty
  // catalog editor flash before the API answers with model_access.
  const [catalogEditable, setCatalogEditable] = useState<boolean | null>(null);
  const [activeService, setActiveService] = useState<ServiceName>("llm");
  const [logs, setLogs] = useState<string>("Waiting for test run...");
  const [testRunning, setTestRunning] = useState<ServiceName | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [toast, setToast] = useState<string>("");
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [providers, setProviders] = useState<
    Record<ServiceName, ProviderOption[]>
  >({ llm: [], embedding: [], search: [] });
  // Most-recent capabilities snapshot from the embedding test run. Cleared
  // when the user kicks off another run, populated when the backend emits
  // the `capabilities` SSE event. Drives the source badge + "Detected: Xd"
  // affordance.
  const [embeddingCapabilities, setEmbeddingCapabilities] =
    useState<EmbeddingCapabilities | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Tour-specific state
  const [tourGuideStep, setTourGuideStep] = useState(-1);

  // -- Data loading -------------------------------------------------------

  useEffect(() => {
    const load = async () => {
      try {
        const settingsResponse = await apiFetch(apiUrl("/api/v1/settings"));
        if (!settingsResponse.ok) {
          throw new Error(`Settings fetch failed: ${settingsResponse.status}`);
        }
        const settingsPayload =
          (await settingsResponse.json()) as SettingsPayload;
        if (settingsPayload.catalog) {
          setCatalog(settingsPayload.catalog);
          setDraft(cloneCatalog(settingsPayload.catalog));
          setCatalogEditable(true);
          setModelAccess(null);
        } else {
          setCatalogEditable(false);
          setModelAccess(settingsPayload.model_access ?? null);
        }
        setTheme(settingsPayload.ui.theme);
        setLanguage(settingsPayload.ui.language);
        if (settingsPayload.providers) setProviders(settingsPayload.providers);
      } catch (err) {
        console.error("Failed to load settings:", err);
      }

      try {
        const statusResponse = await apiFetch(apiUrl("/api/v1/system/status"));
        if (!statusResponse.ok) {
          throw new Error(`Status fetch failed: ${statusResponse.status}`);
        }
        const statusPayload = (await statusResponse.json()) as SystemStatus;
        setStatus(statusPayload);
      } catch (err) {
        console.error("Failed to load system status:", err);
      }
    };
    load();
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  // Reset stale ``embeddingCapabilities`` whenever the active embedding
  // profile or model changes. Without this, a 4096d detection on profile A
  // bleeds into profile B's "Detected: …" affordance after a switch.
  useEffect(() => {
    setEmbeddingCapabilities(null);
  }, [
    draft.services.embedding.active_profile_id,
    draft.services.embedding.active_model_id,
  ]);

  // -- Tour guide auto-switch active service tab --------------------------

  useEffect(() => {
    const currentStep = TOUR_GUIDE_STEPS[tourGuideStep];
    if (currentStep?.service) {
      setActiveService(currentStep.service);
    }
  }, [tourGuideStep]);

  // -- Derived ------------------------------------------------------------

  const settingsLoading = catalogEditable === null;
  const activeProfile = getActiveProfile(draft, activeService);
  const activeModel = getActiveModel(draft, activeService);
  const hasUnsavedChanges =
    catalogEditable === true &&
    JSON.stringify(catalog) !== JSON.stringify(draft);
  const searchProviderRaw =
    activeService === "search"
      ? (activeProfile?.provider || "").trim().toLowerCase()
      : "";
  const showSearchProviderWarning =
    activeService === "search" && Boolean(searchProviderRaw);
  const isDeprecatedSearchProvider =
    deprecatedSearchProviders.has(searchProviderRaw);
  const isSupportedSearchProvider = supportedSearchProviders.includes(
    searchProviderRaw as (typeof supportedSearchProviders)[number],
  );
  const isPerplexityMissingKey =
    activeService === "search" &&
    searchProviderRaw === "perplexity" &&
    !String(activeProfile?.api_key || "").trim();

  // Category-label typography. English looks great with `uppercase` + wide
  // letter-spacing, but CJK glyphs are already square blocks — extra tracking
  // pushes them apart and `uppercase` is a no-op. For zh we drop both and
  // bump size by ~1px to keep visual weight comparable.
  const labelClass = (size: "sm" | "md" | "lg"): string => {
    if (language === "zh") {
      if (size === "sm") return "text-[10.5px] font-medium";
      if (size === "lg") return "text-[12px] font-medium";
      return "text-[11px] font-medium";
    }
    if (size === "sm")
      return "text-[9.5px] font-semibold uppercase tracking-[0.16em]";
    if (size === "lg") return "text-[11px] uppercase tracking-[0.16em]";
    return "text-[10px] font-semibold uppercase tracking-[0.16em]";
  };

  useEffect(() => {
    setShowApiKey(false);
  }, [activeService, activeProfile?.id]);

  // -- UI preference helpers ----------------------------------------------

  const persistUi = async (
    nextTheme: "light" | "dark" | "glass" | "snow",
    nextLanguage: "en" | "zh",
  ) => {
    await apiFetch(apiUrl("/api/v1/settings/ui"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: nextTheme, language: nextLanguage }),
    });
  };

  const updateTheme = async (
    nextTheme: "light" | "dark" | "glass" | "snow",
  ) => {
    setTheme(nextTheme);
    applyThemePreference(nextTheme);
    await persistUi(nextTheme, language);
  };

  const updateLanguage = async (nextLanguage: "en" | "zh") => {
    setLanguage(nextLanguage);
    writeStoredLanguage(nextLanguage);
    await persistUi(theme, nextLanguage);
  };

  // -- Catalog mutations --------------------------------------------------

  const mutateCatalog = (mutator: (next: Catalog) => void) => {
    setDraft((current) => {
      const next = cloneCatalog(current);
      mutator(next);
      return next;
    });
  };

  const embeddingDefaultDim = (binding?: string) => {
    const match = (providers.embedding || []).find(
      (p) => p.value === (binding || "openai"),
    );
    return match?.default_dim || "3072";
  };

  const addProfile = () => {
    mutateCatalog((next) => {
      const service = next.services[activeService];
      const profileId = `${activeService}-profile-${Date.now()}`;
      const profile: CatalogProfile = {
        id: profileId,
        name: "New Profile",
        binding: activeService === "search" ? undefined : "openai",
        provider: activeService === "search" ? "brave" : undefined,
        base_url: "",
        api_key: "",
        api_version: "",
        extra_headers: activeService === "search" ? undefined : {},
        proxy: activeService === "search" ? "" : undefined,
        models: [],
      };
      if (activeService !== "search") {
        const modelId = `${activeService}-model-${Date.now()}`;
        profile.models.push({
          id: modelId,
          name: "New Model",
          model: "",
          ...(activeService === "embedding"
            ? { dimension: embeddingDefaultDim(), send_dimensions: true }
            : {}),
        });
        service.active_model_id = modelId;
      }
      service.profiles.push(profile);
      service.active_profile_id = profileId;
    });
  };

  const removeActiveProfile = () => {
    mutateCatalog((next) => {
      const service = next.services[activeService];
      service.profiles = service.profiles.filter(
        (profile) => profile.id !== service.active_profile_id,
      );
      service.active_profile_id = service.profiles[0]?.id ?? null;
      if (activeService !== "search") {
        service.active_model_id = service.profiles[0]?.models?.[0]?.id ?? null;
      }
    });
  };

  const addModel = () => {
    if (activeService === "search") return;
    mutateCatalog((next) => {
      const service = next.services[activeService];
      const profile =
        service.profiles.find(
          (item) => item.id === service.active_profile_id,
        ) ?? null;
      if (!profile) return;
      const modelId = `${activeService}-model-${Date.now()}`;
      profile.models.push({
        id: modelId,
        name: "New Model",
        model: "",
        ...(activeService === "embedding"
          ? {
              dimension: embeddingDefaultDim(profile.binding),
              send_dimensions: true,
            }
          : {}),
      });
      service.active_model_id = modelId;
    });
  };

  const removeActiveModel = () => {
    if (activeService === "search") return;
    mutateCatalog((next) => {
      const service = next.services[activeService];
      const profile =
        service.profiles.find(
          (item) => item.id === service.active_profile_id,
        ) ?? null;
      if (!profile) return;
      profile.models = profile.models.filter(
        (item) => item.id !== service.active_model_id,
      );
      service.active_model_id = profile.models[0]?.id ?? null;
    });
  };

  const updateProfileField = (field: keyof CatalogProfile, value: string) => {
    mutateCatalog((next) => {
      const profile = getActiveProfile(next, activeService);
      if (!profile) return;
      (profile[field] as string | undefined) = value;
    });
  };

  const updateModelField = (field: keyof CatalogModel, value: string) => {
    if (activeService === "search") return;
    mutateCatalog((next) => {
      const model = getActiveModel(next, activeService);
      if (!model) return;
      (model[field] as string | undefined) = value;
    });
  };

  const updateContextWindowField = (value: string) => {
    if (activeService !== "llm") return;
    const normalized = value.replace(/[^\d]/g, "");
    mutateCatalog((next) => {
      const model = getActiveModel(next, activeService);
      if (!model) return;
      if (normalized) {
        model.context_window = normalized;
        model.context_window_source = "manual";
        delete model.context_window_detected_at;
      } else {
        delete model.context_window;
        delete model.context_window_source;
        delete model.context_window_detected_at;
      }
    });
  };

  const updateModelBoolField = (field: keyof CatalogModel, value: boolean) => {
    if (activeService === "search") return;
    mutateCatalog((next) => {
      const model = getActiveModel(next, activeService);
      if (!model) return;
      (model[field] as boolean | undefined) = value;
    });
  };

  // -- Save / Apply -------------------------------------------------------

  const saveCatalog = async () => {
    if (!catalogEditable) return;
    setSaving(true);
    try {
      const response = await apiFetch(apiUrl("/api/v1/settings/catalog"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog: draft }),
      });
      const payload = await response.json();
      setCatalog(payload.catalog);
      setDraft(cloneCatalog(payload.catalog));
      setToast(t("Draft saved"));
    } finally {
      setSaving(false);
    }
  };

  const applyCatalog = async () => {
    if (!catalogEditable) return;
    setApplying(true);
    try {
      const response = await apiFetch(apiUrl("/api/v1/settings/apply"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog: draft }),
      });
      const payload = await response.json();
      setCatalog(payload.catalog);
      setDraft(cloneCatalog(payload.catalog));
      setToast(t("Applied to .env"));
      const statusResponse = await apiFetch(apiUrl("/api/v1/system/status"));
      setStatus((await statusResponse.json()) as SystemStatus);
    } finally {
      setApplying(false);
    }
  };

  // -- Diagnostics (existing single-service test) -------------------------

  const runDetailedTest = async () => {
    if (!catalogEditable) return;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setLogs(`Preparing ${activeService} diagnostics...\n`);
    setTestRunning(activeService);
    if (activeService === "embedding") {
      setEmbeddingCapabilities(null);
    }
    try {
      const response = await apiFetch(
        apiUrl(`/api/v1/settings/tests/${activeService}/start`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ catalog: draft }),
        },
      );
      const payload = (await response.json()) as {
        run_id?: string;
        detail?: string;
      };
      if (!response.ok || !payload.run_id) {
        throw new Error(payload.detail || "Could not start diagnostics.");
      }
      const source = new EventSource(
        apiUrl(
          `/api/v1/settings/tests/${activeService}/${payload.run_id}/events`,
        ),
      );
      eventSourceRef.current = source;
      source.onmessage = (event) => {
        const entry = JSON.parse(event.data) as {
          type: string;
          message: string;
          catalog?: Catalog;
          detected_dim?: number;
          default_dim?: number;
          supported_dimensions?: number[];
          supports_variable_dimensions?: boolean;
          model_known?: boolean;
          active_dim?: number;
          active_dim_source?: string;
        };
        setLogs((current) => `${current}[${entry.type}] ${entry.message}\n`);
        if (entry.type === "capabilities") {
          setEmbeddingCapabilities({
            detected_dim: entry.detected_dim,
            default_dim: entry.default_dim,
            supported_dimensions: entry.supported_dimensions,
            supports_variable_dimensions: entry.supports_variable_dimensions,
            model_known: entry.model_known,
            active_dim: entry.active_dim,
            active_dim_source: entry.active_dim_source,
          });
        }
        if (entry.catalog) {
          setCatalog(entry.catalog);
          setDraft(cloneCatalog(entry.catalog));
        }
        if (entry.type === "completed" || entry.type === "failed") {
          source.close();
          eventSourceRef.current = null;
          setTestRunning(null);
          setToast(entry.message);
        }
      };
      source.onerror = () => {
        source.close();
        eventSourceRef.current = null;
        setTestRunning(null);
        setLogs(
          (current) => `${current}[failed] Diagnostics stream disconnected.\n`,
        );
        setToast(t("Diagnostics stream disconnected"));
      };
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not start diagnostics.";
      setLogs((current) => `${current}[failed] ${message}\n`);
      setToast(message);
      setTestRunning(null);
    }
  };

  // -- Tour ---------------------------------------------------------------

  const runTour = useCallback(() => {
    setTourGuideStep(0);
  }, []);

  // ═══════════════════════════════════════════════════════════════════════
  // Render
  // ═══════════════════════════════════════════════════════════════════════

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* ── Header ── */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
              {t("Settings")}
            </h1>
            {toast ? (
              <p className="mt-1 text-[13px] text-[var(--primary)] animate-fade-in">
                {toast}
              </p>
            ) : (
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                {hasUnsavedChanges
                  ? t("Draft has unsaved changes")
                  : t("All changes saved")}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {catalogEditable === true && (
              <>
                <button
                  onClick={runTour}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                >
                  <Rocket className="h-3 w-3" />
                  {t("Tour")}
                </button>
                <button
                  data-tour="tour-save-test"
                  onClick={saveCatalog}
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  {saving ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Save className="h-3 w-3" />
                  )}
                  {t("Save Draft")}
                </button>
                <button
                  data-tour="tour-actions"
                  onClick={applyCatalog}
                  disabled={applying}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
                >
                  {applying ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Wand2 className="h-3 w-3" />
                  )}
                  {t("Apply")}
                </button>
              </>
            )}
          </div>
        </div>

        {/* ── Preferences ── */}
        <div className="mb-5 flex flex-wrap items-center gap-x-8 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[var(--muted-foreground)]">
              {t("Theme")}
            </span>
            <div className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
              {(["snow", "light", "dark", "glass"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => updateTheme(v)}
                  className={`rounded-md px-2.5 py-1 text-[12px] transition-all ${
                    theme === v
                      ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {v === "snow"
                    ? t("Snow")
                    : v === "light"
                      ? t("Light")
                      : v === "dark"
                        ? t("Dark")
                        : t("Glass")}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[var(--muted-foreground)]">
              {t("Language")}
            </span>
            <div className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
              {(["en", "zh"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => updateLanguage(v)}
                  className={`rounded-md px-2.5 py-1 text-[12px] transition-all ${
                    language === v
                      ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {v === "en" ? t("language.english") : t("language.chinese")}
                </button>
              ))}
            </div>
          </div>
        </div>

        {settingsLoading && (
          <div className="mt-5 rounded-2xl border border-[var(--border)]/50 bg-[var(--card)] p-5 animate-pulse">
            <div className="h-4 w-32 rounded bg-[var(--muted)]/60" />
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-20 rounded-xl border border-[var(--border)]/40 bg-[var(--background)]/40"
                />
              ))}
            </div>
          </div>
        )}

        {catalogEditable === false && (
          <>
            {modelAccess && <ModelAccessSummary access={modelAccess} />}
            <p className="mt-5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Model endpoints are assigned by your administrator. You can still personalize theme and language here.",
              )}
            </p>
          </>
        )}

        {/* ── Runtime status ── */}
        {catalogEditable === true && (
          <>
            <div className="mb-8 grid grid-cols-2 overflow-hidden rounded-xl border border-[var(--border)]/60 sm:grid-cols-4">
              <div
                className="px-4 py-3.5"
                title={status?.backend.timestamp || t("Backend status")}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${statusDotClass(
                      status?.backend.status === "online",
                      false,
                    )}`}
                  />
                  <span
                    className={`${labelClass("md")} text-[var(--muted-foreground)]`}
                  >
                    {t("Backend")}
                  </span>
                </div>
                <div className="mt-2 truncate text-[13px] font-medium text-[var(--foreground)]">
                  {status?.backend.status === "online"
                    ? t("Online")
                    : t("Checking")}
                </div>
                <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                  {(() => {
                    const ts = status?.backend.timestamp;
                    if (!ts) return "—";
                    const parsed = new Date(ts);
                    if (Number.isNaN(parsed.getTime())) return "";
                    return parsed.toLocaleTimeString(
                      language === "zh" ? "zh-CN" : "en-US",
                      { hour: "2-digit", minute: "2-digit" },
                    );
                  })()}
                </div>
              </div>

              {SERVICES.map((service, i) => {
                const profile = getActiveProfile(draft, service);
                const model = getActiveModel(draft, service);
                const serviceStatus =
                  service === "llm"
                    ? status?.llm
                    : service === "embedding"
                      ? status?.embeddings
                      : status?.search;
                const runtimeModel =
                  service === "llm"
                    ? status?.llm.model
                    : service === "embedding"
                      ? status?.embeddings.model
                      : undefined;
                const configured =
                  service === "search"
                    ? Boolean(profile?.provider || status?.search.provider)
                    : Boolean(model?.model || runtimeModel);
                const pendingApply = servicePendingApply(
                  catalog,
                  draft,
                  service,
                );
                const detail = activeModelDetail(profile, model, service, t);
                const profileName = profile?.name || t("No profile");
                const isActiveTab = activeService === service;
                const borderClasses =
                  i === 0
                    ? "border-l border-[var(--border)]/40"
                    : i === 1
                      ? "border-t border-[var(--border)]/40 sm:border-t-0 sm:border-l"
                      : "border-t border-l border-[var(--border)]/40 sm:border-t-0";
                return (
                  <button
                    key={service}
                    type="button"
                    onClick={() => setActiveService(service)}
                    title={`${serviceLabel(service, t)} · ${profileName} · ${detail}`}
                    className={`relative px-4 py-3.5 text-left transition-colors ${borderClasses} ${
                      isActiveTab
                        ? "bg-[var(--muted)]/55"
                        : "hover:bg-[var(--muted)]/30"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${statusDotClass(
                          configured,
                          Boolean(serviceStatus?.error),
                        )}`}
                      />
                      <span
                        className={`truncate ${labelClass("md")} text-[var(--muted-foreground)]`}
                      >
                        {serviceLabel(service, t)}
                      </span>
                      {pendingApply && (
                        <span className="ml-auto shrink-0 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                          {t("Pending")}
                        </span>
                      )}
                    </div>
                    <div className="mt-2 truncate text-[13px] font-medium text-[var(--foreground)]">
                      {detail}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                      {profileName}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* ── Service Configuration ── */}
            <div className="mb-8">
              <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-1">
                  {(["llm", "embedding", "search"] as const).map((service) => (
                    <button
                      key={service}
                      data-tour={`tour-${service}`}
                      onClick={() => setActiveService(service)}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                        activeService === service
                          ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {serviceIcon(service)}
                      {service.toUpperCase()}
                      <span className="text-[11px] text-[var(--muted-foreground)]/60">
                        {draft.services[service].profiles.length}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={addProfile}
                    className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                  >
                    <Plus className="h-3 w-3" />
                    {t("Profile")}
                  </button>
                  {activeService !== "search" && (
                    <button
                      onClick={addModel}
                      className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                    >
                      <Plus className="h-3 w-3" />
                      {t("Model")}
                    </button>
                  )}
                </div>
              </div>

              {activeProfile ? (
                <div className="grid grid-cols-[200px_1fr] gap-5">
                  {/* ── Profile list ── */}
                  <div className="space-y-2">
                    {draft.services[activeService].profiles.map((profile) => {
                      const isActive =
                        profile.id ===
                        draft.services[activeService].active_profile_id;
                      const activeProfileModel =
                        activeService === "search"
                          ? null
                          : (profile.models.find(
                              (model) =>
                                model.id ===
                                draft.services[activeService].active_model_id,
                            ) ??
                            profile.models[0] ??
                            null);
                      const profileDetail = activeProfileDetail(
                        profile,
                        activeService,
                        t,
                      );
                      const modelDetail = activeModelDetail(
                        profile,
                        activeProfileModel,
                        activeService,
                        t,
                      );
                      return (
                        <button
                          key={profile.id}
                          onClick={() =>
                            mutateCatalog((next) => {
                              next.services[activeService].active_profile_id =
                                profile.id;
                              if (activeService !== "search") {
                                next.services[activeService].active_model_id =
                                  profile.models[0]?.id ?? null;
                              }
                            })
                          }
                          className={`relative w-full overflow-hidden rounded-xl px-3.5 py-3 text-left transition-colors ${
                            isActive
                              ? "bg-[var(--muted)]/60 text-[var(--foreground)]"
                              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/30"
                          }`}
                        >
                          {isActive && (
                            <span className="absolute inset-y-3 left-0 w-0.5 rounded-r-full bg-[var(--foreground)]/80" />
                          )}
                          <div className="truncate text-[13px] font-semibold">
                            {profile.name}
                          </div>
                          <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                            {profileDetail}
                          </div>
                          {isActive ? (
                            <div className="mt-2.5 border-t border-[var(--border)]/40 pt-2">
                              <div
                                className={`${labelClass("sm")} text-[var(--muted-foreground)]/70`}
                              >
                                {activeService === "search"
                                  ? t("Active provider")
                                  : t("Active model")}
                              </div>
                              <div className="mt-0.5 truncate text-[12px] font-medium text-[var(--foreground)]">
                                {modelDetail}
                              </div>
                            </div>
                          ) : (
                            activeService !== "search" && (
                              <div className="mt-1 text-[11px] text-[var(--muted-foreground)]/60">
                                {t("{{count}} models", {
                                  count: profile.models.length,
                                })}
                              </div>
                            )
                          )}
                        </button>
                      );
                    })}
                    <button
                      onClick={removeActiveProfile}
                      disabled={!activeProfile}
                      className="flex w-full items-center gap-1.5 rounded-lg px-3 py-2 text-[11px] text-[var(--muted-foreground)]/40 transition-colors hover:text-red-500 disabled:opacity-30"
                    >
                      <Trash2 className="h-3 w-3" />
                      {t("Delete profile")}
                    </button>
                  </div>

                  {/* ── Editor ── */}
                  <div className="space-y-5">
                    <div className="rounded-xl border border-[var(--border)] p-5">
                      <div className="mb-4 text-[13px] font-medium text-[var(--foreground)]">
                        {t("Profile")}
                      </div>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <div>
                          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                            {t("Name")}
                          </div>
                          <input
                            className={inputClass}
                            value={activeProfile.name}
                            onChange={(e) =>
                              updateProfileField("name", e.target.value)
                            }
                          />
                        </div>
                        <div>
                          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                            {t("Provider")}
                          </div>
                          <div className="relative">
                            <select
                              className={selectClass}
                              value={
                                activeService === "search"
                                  ? activeProfile.provider || ""
                                  : activeProfile.binding || ""
                              }
                              onChange={(e) => {
                                const val = e.target.value;
                                const field =
                                  activeService === "search"
                                    ? "provider"
                                    : "binding";
                                updateProfileField(field, val);
                                const match = (
                                  providers[activeService] || []
                                ).find((p) => p.value === val);
                                if (match?.base_url) {
                                  updateProfileField(
                                    "base_url",
                                    match.base_url,
                                  );
                                }
                                if (
                                  activeService === "embedding" &&
                                  match?.default_dim
                                ) {
                                  updateModelField(
                                    "dimension",
                                    match.default_dim,
                                  );
                                }
                              }}
                            >
                              <option className={selectOptionClass} value="">
                                {t("Select provider...")}
                              </option>
                              {(providers[activeService] || []).map((p) => (
                                <option
                                  className={selectOptionClass}
                                  key={p.value}
                                  value={p.value}
                                >
                                  {p.label}
                                </option>
                              ))}
                            </select>
                            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
                          </div>
                          {showSearchProviderWarning && (
                            <p
                              className={`mt-1.5 text-[11px] ${
                                isSupportedSearchProvider
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : isDeprecatedSearchProvider
                                    ? "text-amber-600 dark:text-amber-400"
                                    : "text-red-500"
                              }`}
                            >
                              {isSupportedSearchProvider
                                ? isPerplexityMissingKey
                                  ? t(
                                      "Perplexity requires API key. It will fail hard without credentials.",
                                    )
                                  : t("Supported provider.")
                                : isDeprecatedSearchProvider
                                  ? t(
                                      "Deprecated provider. Switch to brave/tavily/jina/searxng/duckduckgo/perplexity.",
                                    )
                                  : t(
                                      "Unsupported provider. Use brave/tavily/jina/searxng/duckduckgo/perplexity.",
                                    )}
                            </p>
                          )}
                        </div>
                        <div className="sm:col-span-2">
                          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                            {activeService === "embedding"
                              ? t("Endpoint URL")
                              : t("Base URL")}
                          </div>
                          <input
                            className={inputClass}
                            value={activeProfile.base_url}
                            onChange={(e) =>
                              updateProfileField("base_url", e.target.value)
                            }
                            placeholder={
                              activeService === "embedding"
                                ? "https://api.openai.com/v1/embeddings"
                                : "https://api.openai.com/v1"
                            }
                          />
                          {activeService === "embedding" && (
                            <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
                              {t(
                                "Embedding requests are sent to this URL exactly; DeepTutor does not append /embeddings or /api/embed at request time.",
                              )}
                            </p>
                          )}
                        </div>
                        <div className="sm:col-span-2">
                          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                            {t("API Key")}
                          </div>
                          <div className="relative">
                            <input
                              type={showApiKey ? "text" : "password"}
                              autoComplete="new-password"
                              spellCheck={false}
                              className={`${inputClass} pr-10 font-mono`}
                              value={activeProfile.api_key}
                              onChange={(e) =>
                                updateProfileField("api_key", e.target.value)
                              }
                              placeholder="sk-..."
                            />
                            <button
                              type="button"
                              onClick={() => setShowApiKey((prev) => !prev)}
                              className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                              aria-label={
                                showApiKey
                                  ? t("Hide API key")
                                  : t("Show API key")
                              }
                              title={
                                showApiKey
                                  ? t("Hide API key")
                                  : t("Show API key")
                              }
                            >
                              {showApiKey ? (
                                <EyeOff className="h-4 w-4" />
                              ) : (
                                <Eye className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </div>
                        <div>
                          <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                            {t("API Version")}
                          </div>
                          <input
                            className={inputClass}
                            value={activeProfile.api_version}
                            onChange={(e) =>
                              updateProfileField("api_version", e.target.value)
                            }
                            placeholder={t("Optional")}
                          />
                        </div>
                        {activeService === "search" ? (
                          <div>
                            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                              {t("Proxy")}
                            </div>
                            <input
                              className={inputClass}
                              value={activeProfile.proxy || ""}
                              onChange={(e) =>
                                updateProfileField("proxy", e.target.value)
                              }
                              placeholder="http://127.0.0.1:7890 (optional)"
                            />
                          </div>
                        ) : (
                          <div className="sm:col-span-2">
                            <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                              {t("Extra Headers (JSON)")}
                            </div>
                            <textarea
                              className={`${inputClass} min-h-[84px] resize-y`}
                              value={stringifyExtraHeaders(
                                activeProfile.extra_headers,
                              )}
                              onChange={(e) =>
                                updateProfileField(
                                  "extra_headers",
                                  e.target.value,
                                )
                              }
                              placeholder='{"APP-Code":"your-app-code"}'
                            />
                          </div>
                        )}
                      </div>
                    </div>

                    {activeService !== "search" && (
                      <div className="rounded-xl border border-[var(--border)] p-5">
                        <div className="mb-4 flex items-center justify-between">
                          <div className="text-[13px] font-medium text-[var(--foreground)]">
                            {t("Models")}
                          </div>
                          <button
                            onClick={removeActiveModel}
                            disabled={!activeModel}
                            className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]/40 transition-colors hover:text-red-500 disabled:opacity-30"
                          >
                            <Trash2 className="h-3 w-3" />
                            {t("Delete")}
                          </button>
                        </div>
                        {activeProfile.models.length > 0 && (
                          <div className="mb-4 flex flex-wrap gap-1.5">
                            {activeProfile.models.map((model) => (
                              <button
                                key={model.id}
                                onClick={() =>
                                  mutateCatalog((next) => {
                                    next.services[
                                      activeService
                                    ].active_model_id = model.id;
                                  })
                                }
                                className={`rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                                  model.id ===
                                  draft.services[activeService].active_model_id
                                    ? "bg-[var(--foreground)] font-medium text-[var(--background)] shadow-sm"
                                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"
                                }`}
                              >
                                <span className="inline-flex items-center gap-1.5">
                                  {model.id ===
                                    draft.services[activeService]
                                      .active_model_id && (
                                    <CheckCircle2 className="h-3 w-3" />
                                  )}
                                  {model.name}
                                </span>
                              </button>
                            ))}
                          </div>
                        )}
                        {activeModel && (
                          <div className="grid gap-4 sm:grid-cols-2">
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Label")}
                              </div>
                              <input
                                className={inputClass}
                                value={activeModel.name}
                                onChange={(e) =>
                                  updateModelField("name", e.target.value)
                                }
                              />
                            </div>
                            <div>
                              <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                {t("Model ID")}
                              </div>
                              <input
                                className={inputClass}
                                value={activeModel.model}
                                onChange={(e) =>
                                  updateModelField("model", e.target.value)
                                }
                                placeholder="gpt-4o"
                              />
                            </div>
                            {activeService === "llm" && (
                              <>
                                <div>
                                  <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
                                    {t("Context Window")}
                                  </div>
                                  <input
                                    className={inputClass}
                                    inputMode="numeric"
                                    value={activeModel.context_window || ""}
                                    onChange={(e) =>
                                      updateContextWindowField(e.target.value)
                                    }
                                    placeholder="65536"
                                  />
                                </div>
                                <div className="rounded-xl border border-[var(--border)]/70 bg-[var(--muted)]/30 px-3.5 py-3">
                                  <div className="flex items-center justify-between gap-3">
                                    <div
                                      className={`${labelClass("lg")} text-[var(--muted-foreground)]/70`}
                                    >
                                      {t("Source")}
                                    </div>
                                    <span className="rounded-full border border-[var(--border)]/70 bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--foreground)]">
                                      {formatContextWindowSource(
                                        activeModel.context_window_source,
                                        t,
                                      )}
                                    </span>
                                  </div>
                                  <p className="mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                                    {activeModel.context_window_source ===
                                    "metadata"
                                      ? t(
                                          "Detected from the provider during the latest LLM test and saved into model_catalog.json.",
                                        )
                                      : activeModel.context_window_source ===
                                          "default"
                                        ? t(
                                            "The provider did not expose a context window, so the runtime fallback was saved during the latest LLM test.",
                                          )
                                        : activeModel.context_window_source ===
                                            "manual"
                                          ? t(
                                              "Manual override from Settings. Save Draft to persist your edit.",
                                            )
                                          : t(
                                              "Run the LLM test to auto-fill this field, or enter a value manually.",
                                            )}
                                  </p>
                                  {activeModel.context_window_detected_at && (
                                    <div className="mt-2 text-[11px] text-[var(--muted-foreground)]/70">
                                      {t("Detected at")}:{" "}
                                      {formatContextWindowUpdatedAt(
                                        activeModel.context_window_detected_at,
                                        language,
                                      )}
                                    </div>
                                  )}
                                </div>
                              </>
                            )}
                            {activeService === "embedding" && (
                              <div>
                                <div className="mb-1.5 flex items-center justify-between gap-2">
                                  <span className="text-[12px] text-[var(--muted-foreground)]">
                                    {t("Dimension")}
                                  </span>
                                  <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--muted-foreground)] select-none">
                                    <input
                                      type="checkbox"
                                      className="h-3 w-3 cursor-pointer accent-[var(--foreground)]"
                                      checked={
                                        activeModel.send_dimensions !== false
                                      }
                                      onChange={(e) =>
                                        updateModelBoolField(
                                          "send_dimensions",
                                          e.target.checked,
                                        )
                                      }
                                    />
                                    <span>{t("Send dimensions")}</span>
                                    <span
                                      tabIndex={0}
                                      className="group/info relative inline-flex cursor-help focus:outline-none"
                                    >
                                      <Info className="h-3 w-3 opacity-50 transition-opacity group-hover/info:opacity-100 group-focus/info:opacity-100" />
                                      <span
                                        role="tooltip"
                                        className="pointer-events-none absolute top-full left-1/2 z-20 mt-1.5 w-64 -translate-x-1/2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2.5 text-[11px] leading-relaxed text-[var(--foreground)] opacity-0 shadow-lg transition-opacity duration-75 group-hover/info:opacity-100 group-focus/info:opacity-100"
                                      >
                                        {t(
                                          "Some embedding models (e.g. Qwen text-embedding-v4) reject the `dimensions` request param. Turn this off if your provider returns HTTP 400.",
                                        )}
                                      </span>
                                    </span>
                                  </label>
                                </div>
                                <DimensionField
                                  activeModel={activeModel}
                                  activeBinding={activeProfile?.binding}
                                  capabilities={embeddingCapabilities}
                                  embeddingDefaultDim={embeddingDefaultDim}
                                  inputClass={inputClass}
                                  onChangeDimension={(value) =>
                                    updateModelField("dimension", value)
                                  }
                                />
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-[var(--border)] py-12 text-center text-[13px] text-[var(--muted-foreground)]">
                  {t("No profiles configured. Add a profile to start.")}
                </div>
              )}
            </div>

            {/* ── Diagnostics ── */}
            <div className="mb-6 rounded-xl border border-[var(--border)]">
              <div className="flex items-center justify-between px-5 py-3.5">
                <button
                  type="button"
                  onClick={() => setDiagnosticsOpen((v) => !v)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  aria-expanded={diagnosticsOpen}
                >
                  <Terminal className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                  <span className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("Diagnostics")}
                  </span>
                  {testRunning && (
                    <Loader2 className="h-3 w-3 animate-spin text-[var(--primary)]" />
                  )}
                </button>
                <div className="ml-3 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      if (!diagnosticsOpen) setDiagnosticsOpen(true);
                      runDetailedTest();
                    }}
                    disabled={testRunning !== null}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
                  >
                    {serviceIcon(activeService)}
                    {t("Run test")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDiagnosticsOpen((v) => !v)}
                    className="text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                    aria-label={
                      diagnosticsOpen
                        ? t("Collapse diagnostics")
                        : t("Expand diagnostics")
                    }
                    aria-expanded={diagnosticsOpen}
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${diagnosticsOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                </div>
              </div>
              {diagnosticsOpen && (
                <div className="border-t border-[var(--border)] px-5 py-4">
                  <p className="mb-3 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                    {t(
                      "Streams config snapshot, request target, response summary, and service-specific validation for the active {{service}} profile.",
                      { service: activeService },
                    )}
                  </p>
                  <pre className="max-h-[360px] overflow-y-auto rounded-lg bg-[#0f0f0f] p-4 font-mono text-[12px] leading-6 text-[#777] dark:bg-[#0a0a0a]">
                    {logs}
                  </pre>
                </div>
              )}
            </div>

            {/* ── Footer note ── */}
            <p className="mt-2 pb-4 text-[11px] leading-relaxed text-[var(--muted-foreground)]/40">
              {t("settings.configNote")}
            </p>
          </>
        )}
      </div>

      {/* ── Spotlight overlay (tour onboarding) ── */}
      {catalogEditable === true &&
        tourGuideStep >= 0 &&
        tourGuideStep < TOUR_GUIDE_STEPS.length && (
          <SpotlightOverlay
            stepIndex={tourGuideStep}
            onNext={() => {
              if (tourGuideStep < TOUR_GUIDE_STEPS.length - 1) {
                setTourGuideStep((s) => s + 1);
              } else {
                setTourGuideStep(-1);
              }
            }}
            onSkip={() => setTourGuideStep(-1)}
          />
        )}
    </div>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  return (
    <Suspense
      fallback={
        <div className="min-h-[50vh] flex items-center justify-center text-[13px] text-[var(--muted-foreground)]">
          {t("Loading settings...")}
        </div>
      }
    >
      <SettingsPageContent />
    </Suspense>
  );
}
