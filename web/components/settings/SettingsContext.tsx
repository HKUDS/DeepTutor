"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { writeStoredLanguage } from "@/context/app-shell-storage";
import type { ModelAccess } from "@/features/multi-user/types";
import { apiFetch, apiUrl } from "@/lib/api";
import { setTheme as applyThemePreference } from "@/lib/theme";
import type { AppLanguage } from "@/lib/ui-languages";

// ─── Domain types ─────────────────────────────────────────────────────────

export type ServiceName = "llm" | "embedding" | "search";

export type CatalogModel = {
  id: string;
  name: string;
  model: string;
  dimension?: string;
  send_dimensions?: boolean;
  supported_dimensions?: string;
  context_window?: string;
  context_window_source?: string;
  context_window_detected_at?: string;
};

export type LlmContextWindowDetection = {
  profileId: string | null;
  modelId: string | null;
  contextWindow: number;
  source: string;
  detail?: string;
  detectedAt?: string;
};

export type CatalogProfile = {
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

export type CatalogService = {
  active_profile_id: string | null;
  active_model_id?: string | null;
  profiles: CatalogProfile[];
};

export type Catalog = {
  version: number;
  services: {
    llm: CatalogService;
    embedding: CatalogService;
    search: CatalogService;
  };
};

export type UiSettings = {
  theme: "light" | "dark" | "glass" | "snow";
  language: AppLanguage;
};

export type ProviderOption = {
  value: string;
  label: string;
  base_url?: string;
  default_dim?: string;
};

export type SystemStatus = {
  backend: { status: string; timestamp: string };
  llm: { status: string; model?: string; error?: string };
  embeddings: { status: string; model?: string; error?: string };
  search: { status: string; provider?: string; error?: string };
};

export type EmbeddingCapabilities = {
  detected_dim?: number;
  default_dim?: number;
  supported_dimensions?: number[];
  supports_variable_dimensions?: boolean;
  model_known?: boolean;
  active_dim?: number;
  active_dim_source?: string;
};

type SettingsPayload = {
  ui: UiSettings;
  catalog?: Catalog;
  model_access?: ModelAccess;
  providers?: Record<ServiceName, ProviderOption[]>;
};

// ─── Tour ──────────────────────────────────────────────────────────────────
//
// The tour now spans routes — each step names the sub-page it lives on so the
// controller can navigate there before the spotlight resolves a target. Adding
// a new step is a matter of pushing onto this list; the overlay reads the
// target via ``data-tour=""`` after the page has rendered.

export type TourStep = {
  target: string;
  route: string;
  titleKey: string;
  descKey: string;
};

// Tour step order MUST match the sidebar order in
// ``web/lib/settings-items.ts`` so navigating the tour walks the user
// down the same list they see on the left.
export const TOUR_STEPS: TourStep[] = [
  {
    target: "tour-appearance",
    route: "/settings/appearance",
    titleKey: "settingsTour.appearance.title",
    descKey: "settingsTour.appearance.desc",
  },
  {
    target: "tour-status",
    route: "/settings/status",
    titleKey: "settingsTour.status.title",
    descKey: "settingsTour.status.desc",
  },
  {
    target: "tour-network",
    route: "/settings/network",
    titleKey: "settingsTour.network.title",
    descKey: "settingsTour.network.desc",
  },
  {
    target: "tour-llm",
    route: "/settings/llm",
    titleKey: "settingsTour.llm.title",
    descKey: "settingsTour.llm.desc",
  },
  {
    target: "tour-embedding",
    route: "/settings/embedding",
    titleKey: "settingsTour.embedding.title",
    descKey: "settingsTour.embedding.desc",
  },
  {
    target: "tour-search",
    route: "/settings/search",
    titleKey: "settingsTour.search.title",
    descKey: "settingsTour.search.desc",
  },
  {
    target: "tour-capabilities",
    route: "/settings/capabilities",
    titleKey: "settingsTour.capabilities.title",
    descKey: "settingsTour.capabilities.desc",
  },
  {
    target: "tour-memory",
    route: "/settings/memory",
    titleKey: "settingsTour.memory.title",
    descKey: "settingsTour.memory.desc",
  },
  {
    target: "tour-mcp",
    route: "/settings/mcp",
    titleKey: "settingsTour.mcp.title",
    descKey: "settingsTour.mcp.desc",
  },
  {
    target: "tour-tools",
    route: "/settings/tools",
    titleKey: "settingsTour.tools.title",
    descKey: "settingsTour.tools.desc",
  },
  {
    target: "tour-actions",
    route: "/settings/llm",
    titleKey: "settingsTour.apply.title",
    descKey: "settingsTour.apply.desc",
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────

export function cloneCatalog(catalog: Catalog): Catalog {
  return JSON.parse(JSON.stringify(catalog)) as Catalog;
}

export function defaultCatalog(): Catalog {
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

export function getActiveProfile(
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

export function getActiveModel(
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

export function servicePendingApply(
  catalog: Catalog,
  draft: Catalog,
  service: ServiceName,
): boolean {
  return (
    JSON.stringify(catalog.services[service]) !==
    JSON.stringify(draft.services[service])
  );
}

function nextModelName(
  models: CatalogModel[],
  language: UiSettings["language"],
): string {
  const prefix =
    language === "zh" ? "模型" : language === "de" ? "Modell " : "Model ";
  const used = new Set(models.map((model) => model.name.trim()));
  let index = models.length + 1;
  while (used.has(`${prefix}${index}`)) {
    index += 1;
  }
  return `${prefix}${index}`;
}

// ─── Context ───────────────────────────────────────────────────────────────

export interface SettingsExtension {
  dirty: boolean;
  save: () => Promise<void>;
}

type SettingsContextValue = {
  // State
  catalog: Catalog;
  draft: Catalog;
  status: SystemStatus | null;
  providers: Record<ServiceName, ProviderOption[]>;
  modelAccess: ModelAccess | null;
  catalogEditable: boolean | null;
  settingsLoading: boolean;
  settingsError: string | null;
  reloadSettings: () => Promise<void>;
  hasUnsavedChanges: boolean;
  theme: UiSettings["theme"];
  language: UiSettings["language"];
  toast: string;
  setToast: (value: string) => void;

  // UI prefs
  updateTheme: (next: UiSettings["theme"]) => Promise<void>;
  updateLanguage: (next: UiSettings["language"]) => Promise<void>;

  // Catalog mutation
  mutateCatalog: (mutator: (next: Catalog) => void) => void;
  addProfile: (service: ServiceName) => void;
  removeActiveProfile: (service: ServiceName) => void;
  addModel: (service: ServiceName) => void;
  removeActiveModel: (service: ServiceName) => void;
  updateProfileField: (
    service: ServiceName,
    field: keyof CatalogProfile,
    value: string,
  ) => void;
  updateModelField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: string,
  ) => void;
  updateModelBoolField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: boolean,
  ) => void;
  updateContextWindowField: (value: string) => void;
  llmContextDetection: LlmContextWindowDetection | null;
  applyDetectedContextWindow: () => void;

  // Save / apply
  saving: boolean;
  applying: boolean;
  saveCatalog: () => Promise<void>;
  applyCatalog: () => Promise<void>;

  // Sub-page extension hooks. Sub-routes (e.g. /settings/memory) that own
  // state outside the catalog register a "dirty + save" pair so the global
  // Apply button can flush them alongside the catalog. Re-register on every
  // render — the latest closure wins.
  registerExtension: (key: string, ext: SettingsExtension | null) => void;

  // Diagnostics
  logs: string;
  testRunning: ServiceName | null;
  embeddingCapabilities: EmbeddingCapabilities | null;
  runDetailedTest: (service: ServiceName) => Promise<void>;

  // Helpers
  embeddingDefaultDim: (binding?: string) => string;

  // Tour
  tourStepIndex: number;
  startTour: () => void;
  advanceTour: () => void;
  goBackTour: () => void;
  skipTour: () => void;
};

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) {
    throw new Error("useSettings must be used inside <SettingsProvider>");
  }
  return ctx;
}

// ─── Provider ──────────────────────────────────────────────────────────────

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const router = useRouter();

  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [theme, setTheme] = useState<UiSettings["theme"]>("light");
  const [language, setLanguage] = useState<UiSettings["language"]>("en");
  const [catalog, setCatalog] = useState<Catalog>(defaultCatalog());
  const [draft, setDraft] = useState<Catalog>(defaultCatalog());
  const [modelAccess, setModelAccess] = useState<ModelAccess | null>(null);
  const [catalogEditable, setCatalogEditable] = useState<boolean | null>(null);
  const [providers, setProviders] = useState<
    Record<ServiceName, ProviderOption[]>
  >({ llm: [], embedding: [], search: [] });
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  // Empty string is the "no diagnostics yet" sentinel; the editor renders
  // a localized placeholder when logs is falsy. Don't seed an English
  // literal here — older code did, then read it back via .startsWith.
  const [logs, setLogs] = useState<string>("");
  const [testRunning, setTestRunning] = useState<ServiceName | null>(null);
  const [llmContextDetection, setLlmContextDetection] =
    useState<LlmContextWindowDetection | null>(null);
  const [embeddingCapabilities, setEmbeddingCapabilities] =
    useState<EmbeddingCapabilities | null>(null);
  const [tourStepIndex, setTourStepIndex] = useState(-1);
  const eventSourceRef = useRef<EventSource | null>(null);
  // Extensions register their latest dirty/save on each render. We track
  // a "version" counter to trigger re-renders for `hasUnsavedChanges`
  // when an extension's dirty flag flips.
  const extensionsRef = useRef<Map<string, SettingsExtension>>(new Map());
  const [extensionsVersion, setExtensionsVersion] = useState(0);
  const registerExtension = useCallback(
    (key: string, ext: SettingsExtension | null) => {
      const map = extensionsRef.current;
      const prev = map.get(key);
      if (ext === null) {
        if (prev === undefined) return;
        map.delete(key);
        setExtensionsVersion((n) => n + 1);
        return;
      }
      if (prev && prev.dirty === ext.dirty && prev.save === ext.save) {
        return;
      }
      map.set(key, ext);
      // Only bump version when dirty flips — save fn changes every render
      // are common and should not re-render the toolbar.
      if (prev?.dirty !== ext.dirty) {
        setExtensionsVersion((n) => n + 1);
      }
    },
    [],
  );

  const [settingsError, setSettingsError] = useState<string | null>(null);

  // Single load step. Kept separate from the mount effect so a "Retry" action
  // can re-run it without remounting the provider.
  const loadSettings = useCallback(async () => {
    setSettingsError(null);
    let settingsLoaded = false;
    try {
      const settingsResponse = await apiFetch(apiUrl("/api/v1/settings"));
      if (!settingsResponse.ok) {
        throw new Error(
          `Settings fetch failed: HTTP ${settingsResponse.status}`,
        );
      }
      const payload = (await settingsResponse.json()) as SettingsPayload;
      if (payload.catalog) {
        setCatalog(payload.catalog);
        setDraft(cloneCatalog(payload.catalog));
        setCatalogEditable(true);
        setModelAccess(null);
      } else {
        setCatalogEditable(false);
        setModelAccess(payload.model_access ?? null);
      }
      setTheme(payload.ui.theme);
      setLanguage(payload.ui.language);
      if (payload.providers) setProviders(payload.providers);
      settingsLoaded = true;
    } catch (err) {
      console.error("Failed to load settings:", err);
      const message = err instanceof Error ? err.message : String(err);
      setSettingsError(message);
      // Resolve the loading gate so the page can render the error UI instead
      // of staying in an infinite skeleton state.
      setCatalogEditable((current) => (current === null ? false : current));
    }
    try {
      const statusResponse = await apiFetch(apiUrl("/api/v1/system/status"));
      if (statusResponse.ok) {
        setStatus((await statusResponse.json()) as SystemStatus);
      }
    } catch (err) {
      console.error("Failed to load system status:", err);
      // Only surface this when settings itself loaded; otherwise the
      // settings-fetch error already explains the disconnect.
      if (settingsLoaded) {
        setSettingsError(
          (current) =>
            current ??
            (err instanceof Error
              ? t("System status unavailable: {{message}}", {
                  message: err.message,
                })
              : t("System status unavailable.")),
        );
      }
    }
  }, [t]);

  // Load settings + status once on mount. Subsequent navigations between
  // settings sub-pages share this state via the layout-level provider.
  useEffect(() => {
    loadSettings();
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, [loadSettings]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  // ── UI preferences ──────────────────────────────────────────────────────
  const persistUi = useCallback(
    async (
      nextTheme: UiSettings["theme"],
      nextLanguage: UiSettings["language"],
    ) => {
      await apiFetch(apiUrl("/api/v1/settings/ui"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: nextTheme, language: nextLanguage }),
      });
    },
    [],
  );

  const updateTheme = useCallback(
    async (next: UiSettings["theme"]) => {
      setTheme(next);
      applyThemePreference(next);
      await persistUi(next, language);
    },
    [language, persistUi],
  );

  const updateLanguage = useCallback(
    async (next: UiSettings["language"]) => {
      setLanguage(next);
      writeStoredLanguage(next);
      await persistUi(theme, next);
    },
    [persistUi, theme],
  );

  // ── Catalog mutators ────────────────────────────────────────────────────
  const mutateCatalog = useCallback((mutator: (next: Catalog) => void) => {
    setDraft((current) => {
      const next = cloneCatalog(current);
      mutator(next);
      return next;
    });
  }, []);

  const embeddingDefaultDim = useCallback(
    (binding?: string) => {
      const match = (providers.embedding || []).find(
        (p) => p.value === (binding || "openai"),
      );
      return match?.default_dim || "3072";
    },
    [providers.embedding],
  );

  const addProfile = useCallback(
    (service: ServiceName) => {
      mutateCatalog((next) => {
        const target = next.services[service];
        const profileId = `${service}-profile-${Date.now()}`;
        const defaultBinding = service === "search" ? undefined : "openai";
        const defaultProvider = service === "search" ? "brave" : undefined;
        const providerKey =
          service === "search" ? defaultProvider : defaultBinding;
        const providerLabel =
          (providers[service] || []).find((p) => p.value === providerKey)
            ?.label ??
          providerKey ??
          "New Profile";
        const profile: CatalogProfile = {
          id: profileId,
          name: providerLabel,
          binding: defaultBinding,
          provider: defaultProvider,
          base_url: "",
          api_key: "",
          api_version: "",
          extra_headers: service === "search" ? undefined : {},
          proxy: service === "search" ? "" : undefined,
          models: [],
        };
        if (service !== "search") {
          const modelId = `${service}-model-${Date.now()}`;
          const modelName = nextModelName([], language);
          profile.models.push({
            id: modelId,
            name: modelName,
            model: "",
            ...(service === "embedding"
              ? {
                  dimension: embeddingDefaultDim(),
                  send_dimensions: true,
                }
              : {}),
          });
          target.active_model_id = modelId;
        }
        target.profiles.push(profile);
        target.active_profile_id = profileId;
      });
    },
    [embeddingDefaultDim, language, mutateCatalog, providers],
  );

  const removeActiveProfile = useCallback(
    (service: ServiceName) => {
      mutateCatalog((next) => {
        const target = next.services[service];
        target.profiles = target.profiles.filter(
          (profile) => profile.id !== target.active_profile_id,
        );
        target.active_profile_id = target.profiles[0]?.id ?? null;
        if (service !== "search") {
          target.active_model_id = target.profiles[0]?.models?.[0]?.id ?? null;
        }
      });
    },
    [mutateCatalog],
  );

  const addModel = useCallback(
    (service: ServiceName) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile =
          target.profiles.find(
            (item) => item.id === target.active_profile_id,
          ) ?? null;
        if (!profile) return;
        const modelId = `${service}-model-${Date.now()}`;
        const modelName = nextModelName(profile.models, language);
        profile.models.push({
          id: modelId,
          name: modelName,
          model: "",
          ...(service === "embedding"
            ? {
                dimension: embeddingDefaultDim(profile.binding),
                send_dimensions: true,
              }
            : {}),
        });
        target.active_model_id = modelId;
      });
    },
    [embeddingDefaultDim, language, mutateCatalog],
  );

  const removeActiveModel = useCallback(
    (service: ServiceName) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile =
          target.profiles.find(
            (item) => item.id === target.active_profile_id,
          ) ?? null;
        if (!profile) return;
        profile.models = profile.models.filter(
          (item) => item.id !== target.active_model_id,
        );
        target.active_model_id = profile.models[0]?.id ?? null;
      });
    },
    [mutateCatalog],
  );

  const updateProfileField = useCallback(
    (service: ServiceName, field: keyof CatalogProfile, value: string) => {
      mutateCatalog((next) => {
        const profile = getActiveProfile(next, service);
        if (!profile) return;
        (profile[field] as string | undefined) = value;
      });
    },
    [mutateCatalog],
  );

  const updateModelField = useCallback(
    (service: ServiceName, field: keyof CatalogModel, value: string) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = getActiveModel(next, service);
        if (!model) return;
        (model[field] as string | undefined) = value;
      });
    },
    [mutateCatalog],
  );

  const updateModelBoolField = useCallback(
    (service: ServiceName, field: keyof CatalogModel, value: boolean) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = getActiveModel(next, service);
        if (!model) return;
        (model[field] as boolean | undefined) = value;
      });
    },
    [mutateCatalog],
  );

  const updateContextWindowField = useCallback(
    (value: string) => {
      const normalized = value.replace(/[^\d]/g, "");
      mutateCatalog((next) => {
        const model = getActiveModel(next, "llm");
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
    },
    [mutateCatalog],
  );

  const applyDetectedContextWindow = useCallback(() => {
    if (!llmContextDetection) return;
    mutateCatalog((next) => {
      const target = next.services.llm;
      if (
        target.active_profile_id !== llmContextDetection.profileId ||
        target.active_model_id !== llmContextDetection.modelId
      ) {
        return;
      }
      const model = getActiveModel(next, "llm");
      if (!model) return;
      model.context_window = String(llmContextDetection.contextWindow);
      model.context_window_source = llmContextDetection.source;
      if (llmContextDetection.detectedAt) {
        model.context_window_detected_at = llmContextDetection.detectedAt;
      } else {
        delete model.context_window_detected_at;
      }
    });
    setToast(t("Detected context window written to draft"));
  }, [llmContextDetection, mutateCatalog, t]);

  // ── Save / Apply ────────────────────────────────────────────────────────
  const saveCatalog = useCallback(async () => {
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
  }, [catalogEditable, draft, t]);

  const applyCatalog = useCallback(async () => {
    setApplying(true);
    try {
      // Flush extensions (e.g. /settings/memory) first so their saved
      // state is visible to any backend side-effects in /apply below.
      const exts = Array.from(extensionsRef.current.values()).filter(
        (e) => e.dirty,
      );
      await Promise.all(exts.map((e) => e.save()));

      // The catalog apply is only meaningful when editable; an extension-
      // only flush should still produce a success toast.
      if (catalogEditable) {
        const response = await apiFetch(apiUrl("/api/v1/settings/apply"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ catalog: draft }),
        });
        const payload = await response.json();
        setCatalog(payload.catalog);
        setDraft(cloneCatalog(payload.catalog));
        const statusResponse = await apiFetch(apiUrl("/api/v1/system/status"));
        setStatus((await statusResponse.json()) as SystemStatus);
      }
      setToast(t("Applied to runtime settings"));
    } finally {
      setApplying(false);
    }
  }, [catalogEditable, draft, t]);

  // ── Diagnostics ─────────────────────────────────────────────────────────
  // Reset capability snapshot when switching embedding profile/model so a
  // stale "Detected: Xd" hint doesn't bleed across profiles.
  useEffect(() => {
    setEmbeddingCapabilities(null);
  }, [
    draft.services.embedding.active_profile_id,
    draft.services.embedding.active_model_id,
  ]);

  useEffect(() => {
    setLlmContextDetection((current) => {
      if (!current) return null;
      const llm = draft.services.llm;
      if (
        current.profileId === llm.active_profile_id &&
        current.modelId === llm.active_model_id
      ) {
        return current;
      }
      return null;
    });
  }, [
    draft.services.llm.active_profile_id,
    draft.services.llm.active_model_id,
  ]);

  const runDetailedTest = useCallback(
    async (service: ServiceName) => {
      if (!catalogEditable) return;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setLogs(t("Preparing {{service}} diagnostics...", { service }) + "\n");
      setTestRunning(service);
      const runProfileId =
        service === "llm" ? draft.services.llm.active_profile_id : null;
      const runModelId =
        service === "llm" ? (draft.services.llm.active_model_id ?? null) : null;
      if (service === "llm") setLlmContextDetection(null);
      if (service === "embedding") setEmbeddingCapabilities(null);
      try {
        const response = await apiFetch(
          apiUrl(`/api/v1/settings/tests/${service}/start`),
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
          throw new Error(payload.detail || t("Could not start diagnostics."));
        }
        const source = new EventSource(
          apiUrl(`/api/v1/settings/tests/${service}/${payload.run_id}/events`),
          { withCredentials: true },
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
            context_window?: number;
            source?: string;
            detail?: string;
            detected_at?: string;
          };
          setLogs((current) => `${current}[${entry.type}] ${entry.message}\n`);
          if (service === "llm" && entry.type === "context_window") {
            const detected =
              typeof entry.context_window === "number"
                ? entry.context_window
                : Number.parseInt(String(entry.context_window ?? ""), 10);
            if (Number.isFinite(detected) && detected > 0) {
              setLlmContextDetection({
                profileId: runProfileId,
                modelId: runModelId,
                contextWindow: detected,
                source: entry.source || "metadata",
                detail: entry.detail,
                detectedAt: entry.detected_at,
              });
            }
          }
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
            (current) =>
              `${current}[failed] ${t("Diagnostics stream disconnected.")}\n`,
          );
          setToast(t("Diagnostics stream disconnected"));
        };
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : t("Could not start diagnostics.");
        setLogs((current) => `${current}[failed] ${message}\n`);
        setToast(message);
        setTestRunning(null);
      }
    },
    [catalogEditable, draft, t],
  );

  // ── Tour ────────────────────────────────────────────────────────────────
  // The tour drives a SpotlightOverlay rendered by the layout. When the step
  // changes, we navigate to the step's route; the overlay then resolves the
  // target via data-tour after the page renders.
  const startTour = useCallback(() => {
    if (TOUR_STEPS.length === 0) return;
    setTourStepIndex(0);
    // No router.push here — the route-sync effect below handles it,
    // and doing it in two places would issue a redundant push.
  }, []);

  // Pure state updaters — DO NOT call router.push inside these. React
  // may invoke the updater twice in StrictMode, and triggering a
  // separate component's setState (Router) from inside a setState
  // callback raises "Cannot update a component while rendering another".
  // The route is synced via the effect below.
  const advanceTour = useCallback(() => {
    setTourStepIndex((idx) => {
      const nextIdx = idx + 1;
      return nextIdx >= TOUR_STEPS.length ? -1 : nextIdx;
    });
  }, []);

  const goBackTour = useCallback(() => {
    setTourStepIndex((idx) => (idx > 0 ? idx - 1 : idx));
  }, []);

  const skipTour = useCallback(() => {
    setTourStepIndex(-1);
  }, []);

  // Sync the URL to the current tour step. Runs after render commits
  // so it never re-enters another component's render.
  useEffect(() => {
    if (tourStepIndex < 0 || tourStepIndex >= TOUR_STEPS.length) return;
    const step = TOUR_STEPS[tourStepIndex];
    router.push(step.route);
  }, [tourStepIndex, router]);

  // ── Derived ─────────────────────────────────────────────────────────────
  const hasUnsavedChanges = useMemo(() => {
    const catalogDirty =
      catalogEditable === true &&
      JSON.stringify(catalog) !== JSON.stringify(draft);
    if (catalogDirty) return true;
    // Any registered extension dirty also counts. Reading from the ref is
    // safe because `extensionsVersion` invalidates this memo on flip.
    for (const ext of extensionsRef.current.values()) {
      if (ext.dirty) return true;
    }
    return false;
  }, [catalog, catalogEditable, draft, extensionsVersion]);

  const settingsLoading = catalogEditable === null;

  const value = useMemo<SettingsContextValue>(
    () => ({
      catalog,
      draft,
      status,
      providers,
      modelAccess,
      catalogEditable,
      settingsLoading,
      settingsError,
      reloadSettings: loadSettings,
      hasUnsavedChanges,
      theme,
      language,
      toast,
      setToast,
      updateTheme,
      updateLanguage,
      mutateCatalog,
      addProfile,
      removeActiveProfile,
      addModel,
      removeActiveModel,
      updateProfileField,
      updateModelField,
      updateModelBoolField,
      updateContextWindowField,
      llmContextDetection,
      applyDetectedContextWindow,
      saving,
      applying,
      saveCatalog,
      applyCatalog,
      registerExtension,
      logs,
      testRunning,
      embeddingCapabilities,
      runDetailedTest,
      embeddingDefaultDim,
      tourStepIndex,
      startTour,
      advanceTour,
      goBackTour,
      skipTour,
    }),
    [
      addModel,
      addProfile,
      applyDetectedContextWindow,
      applyCatalog,
      applying,
      catalog,
      catalogEditable,
      draft,
      embeddingCapabilities,
      embeddingDefaultDim,
      hasUnsavedChanges,
      language,
      llmContextDetection,
      logs,
      modelAccess,
      mutateCatalog,
      providers,
      registerExtension,
      removeActiveModel,
      removeActiveProfile,
      runDetailedTest,
      saveCatalog,
      saving,
      settingsError,
      loadSettings,
      settingsLoading,
      skipTour,
      startTour,
      advanceTour,
      goBackTour,
      status,
      testRunning,
      theme,
      toast,
      tourStepIndex,
      updateContextWindowField,
      updateLanguage,
      updateModelBoolField,
      updateModelField,
      updateProfileField,
      updateTheme,
    ],
  );

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
}
