/* eslint-disable i18n/no-literal-ui-text */
"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  Brain,
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
import { apiUrl } from "@/lib/api";
import { setTheme as applyThemePreference } from "@/lib/theme";

type ServiceName = "llm" | "embedding" | "search";

type CatalogModel = {
  id: string;
  name: string;
  model: string;
  dimension?: string;
  send_dimensions?: boolean;
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
  catalog: Catalog;
  providers?: Record<ServiceName, ProviderOption[]>;
};

type SystemStatus = {
  backend: { status: string; timestamp: string };
  llm: { status: string; model?: string; error?: string };
  embeddings: { status: string; model?: string; error?: string };
  search: { status: string; provider?: string; error?: string };
};

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

const inputClass =
  "w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] placeholder:text-[var(--muted-foreground)]/40";

const selectClass =
  "w-full appearance-none rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)] cursor-pointer";

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
    const frame = window.requestAnimationFrame(() => {
      if (!guideStep) {
        setRect(null);
        return;
      }
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
  const eventSourceRef = useRef<EventSource | null>(null);

  // Tour-specific state
  const [tourGuideStep, setTourGuideStep] = useState(-1);

  // -- Data loading -------------------------------------------------------

  useEffect(() => {
    const load = async () => {
      const settingsResponse = await fetch(apiUrl("/api/v1/settings"));
      const settingsPayload =
        (await settingsResponse.json()) as SettingsPayload;
      setCatalog(settingsPayload.catalog);
      setDraft(cloneCatalog(settingsPayload.catalog));
      setTheme(settingsPayload.ui.theme);
      setLanguage(settingsPayload.ui.language);
      if (settingsPayload.providers) setProviders(settingsPayload.providers);

      const statusResponse = await fetch(apiUrl("/api/v1/system/status"));
      const statusPayload = (await statusResponse.json()) as SystemStatus;
      setStatus(statusPayload);
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

  // -- Tour guide auto-switch active service tab --------------------------

  useEffect(() => {
    const currentStep = TOUR_GUIDE_STEPS[tourGuideStep];
    if (currentStep?.service) {
      setActiveService(currentStep.service);
    }
  }, [tourGuideStep]);

  // -- Derived ------------------------------------------------------------

  const activeProfile = getActiveProfile(draft, activeService);
  const activeModel = getActiveModel(draft, activeService);
  const hasUnsavedChanges = JSON.stringify(catalog) !== JSON.stringify(draft);
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

  useEffect(() => {
    setShowApiKey(false);
  }, [activeService, activeProfile?.id]);

  // -- UI preference helpers ----------------------------------------------

  const persistUi = async (
    nextTheme: "light" | "dark" | "glass" | "snow",
    nextLanguage: "en" | "zh",
  ) => {
    await fetch(apiUrl("/api/v1/settings/ui"), {
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
    setSaving(true);
    try {
      const response = await fetch(apiUrl("/api/v1/settings/catalog"), {
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
    setApplying(true);
    try {
      const response = await fetch(apiUrl("/api/v1/settings/apply"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog: draft }),
      });
      const payload = await response.json();
      setCatalog(payload.catalog);
      setDraft(cloneCatalog(payload.catalog));
      setToast(t("Applied to .env"));
      const statusResponse = await fetch(apiUrl("/api/v1/system/status"));
      setStatus((await statusResponse.json()) as SystemStatus);
    } finally {
      setApplying(false);
    }
  };

  // -- Diagnostics (existing single-service test) -------------------------

  const runDetailedTest = async () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setLogs(`Preparing ${activeService} diagnostics...\n`);
    setTestRunning(activeService);
    try {
      const response = await fetch(
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
        };
        setLogs((current) => `${current}[${entry.type}] ${entry.message}\n`);
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
      <div className="mx-auto max-w-[960px] px-4 py-5 sm:px-6 sm:py-8">
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
          </div>
        </div>

        {/* ── Preferences & Runtime ── */}
        <div className="mb-8 flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-[var(--border)]/50 pb-6">
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

          <div className="ml-0 mt-3 flex w-full flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-[var(--muted-foreground)] sm:ml-auto sm:mt-0 sm:w-auto">
            <span className="flex items-center gap-1.5">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${statusDotClass(status?.backend.status === "online", false)}`}
              />
              {t("Backend")}
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${statusDotClass(Boolean(status?.llm.model), Boolean(status?.llm.error))}`}
              />
              {t("LLM")}
              {status?.llm.model && (
                <span className="text-[var(--muted-foreground)]/50">
                  · {status.llm.model}
                </span>
              )}
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${statusDotClass(Boolean(status?.embeddings.model), Boolean(status?.embeddings.error))}`}
              />
              {t("Emb")}
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${statusDotClass(Boolean(status?.search.provider), false)}`}
              />
              {t("Search")}
            </span>
          </div>
        </div>

        {/* ── Service Configuration ── */}
        <div className="mb-8">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex max-w-full items-center gap-1 overflow-x-auto hide-scrollbar">
              {(["llm", "embedding", "search"] as const).map((service) => (
                <button
                  key={service}
                  data-tour={`tour-${service}`}
                  onClick={() => setActiveService(service)}
                  className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
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
            <div className="flex shrink-0 items-center gap-2">
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
            <div className="grid gap-5 lg:grid-cols-[200px_1fr]">
              {/* ── Profile list ── */}
              <div className="space-y-1">
                {draft.services[activeService].profiles.map((profile) => (
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
                    className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${
                      profile.id ===
                      draft.services[activeService].active_profile_id
                        ? "bg-[var(--muted)] text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"
                    }`}
                  >
                    <div className="text-[13px] font-medium">
                      {profile.name}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                      {profile.base_url || t("No endpoint")}
                    </div>
                  </button>
                ))}
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
                            const match = (providers[activeService] || []).find(
                              (p) => p.value === val,
                            );
                            if (match?.base_url) {
                              updateProfileField("base_url", match.base_url);
                            }
                            if (
                              activeService === "embedding" &&
                              match?.default_dim
                            ) {
                              updateModelField("dimension", match.default_dim);
                            }
                          }}
                        >
                          <option value="">{t("Select provider...")}</option>
                          {(providers[activeService] || []).map((p) => (
                            <option key={p.value} value={p.value}>
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
                        {t("Base URL")}
                      </div>
                      <input
                        className={inputClass}
                        value={activeProfile.base_url}
                        onChange={(e) =>
                          updateProfileField("base_url", e.target.value)
                        }
                        placeholder="https://api.openai.com/v1"
                      />
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
                            showApiKey ? t("Hide API key") : t("Show API key")
                          }
                          title={
                            showApiKey ? t("Hide API key") : t("Show API key")
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
                            updateProfileField("extra_headers", e.target.value)
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
                                next.services[activeService].active_model_id =
                                  model.id;
                              })
                            }
                            className={`rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                              model.id ===
                              draft.services[activeService].active_model_id
                                ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"
                            }`}
                          >
                            {model.name}
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
                                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--muted-foreground)]/70">
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
                            <input
                              className={inputClass}
                              value={
                                activeModel.dimension ||
                                embeddingDefaultDim(activeProfile?.binding)
                              }
                              onChange={(e) =>
                                updateModelField("dimension", e.target.value)
                              }
                              disabled={activeModel.send_dimensions === false}
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
      </div>

      {/* ── Spotlight overlay (tour onboarding) ── */}
      {tourGuideStep >= 0 && tourGuideStep < TOUR_GUIDE_STEPS.length && (
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
