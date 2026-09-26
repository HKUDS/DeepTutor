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

import type { CodeBlockThemeId } from "@/components/common/code-block-themes";
import {
  normalizeCodeBlockTheme,
  writeStoredCodeBlockShowLineNumbers,
  writeStoredCodeBlockTheme,
  writeStoredCodeBlockWrapLongLines,
  writeStoredLanguage,
  writeStoredResponseLanguage,
  type ResponseLanguage,
} from "@/context/app-shell-storage";
import { useAppShell } from "@/context/AppShellContext";
import type { AppLanguage } from "@/i18n/languages";
import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateLLMOptionsCache } from "@/lib/llm-options";
import { setModelReasoningEffort } from "@/lib/reasoning-effort";
import { applyExtensionPayload } from "@/lib/settings-extensions";
import { setTheme as applyThemePreference } from "@/lib/theme";
import {
  detachProfileConnection,
  modelTestKey,
  reconcileProviderSave,
  modelTestFingerprint,
  type ModelTestState,
} from "@/lib/model-settings";
import {
  reconcileRegistrySave,
  type RegistryEdit,
} from "@/lib/provider-registry";
import { browserStorage } from "@/shared/storage";

import {
  CONNECTABLE_SERVICES,
  type ProviderRef,
  type Discovery,
  type ServiceName,
  type ModelCapabilities,
  type ModelCapabilityKey,
  type ApiFormat,
  type CatalogModel,
  type LlmContextWindowDetection,
  type CatalogProfile,
  type CatalogService,
  type CatalogConnection,
  type ConnectionTargetService,
  type ConnectionTarget,
  type Catalog,
  type ProviderOption,
  type CatalogTaskOverride,
  type TaskKindInfo,
} from "@/lib/model-catalog-types";
export { CONNECTABLE_SERVICES } from "@/lib/model-catalog-types";
export type {
  ProviderRef,
  Discovery,
  ServiceName,
  ModelCapabilities,
  ModelCapabilityKey,
  ApiFormat,
  CatalogModel,
  LlmContextWindowDetection,
  CatalogProfile,
  CatalogService,
  CatalogTaskOverride,
  TaskKindInfo,
  CatalogConnection,
  ConnectionTargetService,
  ConnectionTarget,
  Catalog,
  ProviderOption,
} from "@/lib/model-catalog-types";

// ─── Domain types ─────────────────────────────────────────────────────────

export type UiSettings = {
  theme: "light" | "dark" | "glass" | "snow";
  language: AppLanguage;
  response_language: ResponseLanguage;
  code_block_theme: string;
  code_block_show_line_numbers: boolean;
  code_block_wrap_long_lines: boolean;
};

export type ResponseLanguageOption = {
  value: ResponseLanguage;
  label: string;
};

export const RESPONSE_LANGUAGE_OPTIONS: readonly ResponseLanguageOption[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "简体中文" },
  { value: "zh-tw", label: "繁體中文" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "ru", label: "Русский" },
  { value: "pt", label: "Português" },
  { value: "it", label: "Italiano" },
  { value: "ar", label: "العربية" },
  { value: "pl", label: "Polski" },
  { value: "uk", label: "Українська" },
];

type CodeBlockUiSettings = Pick<
  UiSettings,
  | "code_block_theme"
  | "code_block_show_line_numbers"
  | "code_block_wrap_long_lines"
>;

type UiSettingsPatch = Partial<UiSettings>;

export function syncLoadedCodeBlockSettingsToAppShell(
  ui: Partial<CodeBlockUiSettings>,
): CodeBlockUiSettings {
  const normalized = {
    code_block_theme: normalizeCodeBlockTheme(ui.code_block_theme),
    code_block_show_line_numbers:
      ui.code_block_show_line_numbers === true ||
      String(ui.code_block_show_line_numbers).toLowerCase() === "true",
    code_block_wrap_long_lines:
      ui.code_block_wrap_long_lines === true ||
      String(ui.code_block_wrap_long_lines).toLowerCase() === "true",
  };

  writeStoredCodeBlockTheme(normalized.code_block_theme);
  writeStoredCodeBlockShowLineNumbers(normalized.code_block_show_line_numbers);
  writeStoredCodeBlockWrapLongLines(normalized.code_block_wrap_long_lines);

  return normalized;
}

export async function persistUiSettingsPatch(
  patch: UiSettingsPatch,
  fetcher: typeof apiFetch = apiFetch,
): Promise<void> {
  await fetcher(apiUrl("/api/settings/ui"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

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

export type DiagnosticsResult = {
  state: "success" | "failed";
  message: string;
  profileId: string | null;
  modelId: string | null;
};

export type ServiceReadiness =
  "not_configured" | "untested" | "passed" | "failed";

/**
 * Where the current settings state lives.
 *   clean   — identical to what is applied
 *   unsaved — edited, not written anywhere yet
 *   saved   — written to the draft store, not applied
 */
export type DraftState = "clean" | "unsaved" | "saved";

/** What the server holds as unapplied. `catalog` comes back redacted. */
export type StoredDraft = {
  version: number;
  updated_at: string;
  catalog: Catalog | null;
  extensions: Record<string, unknown>;
};

type SettingsPayload = {
  ui: UiSettings;
  catalog?: Catalog;
  providers?: Record<ServiceName, ProviderOption[]>;
  connection_targets?: ConnectionTarget[];
  task_kinds?: TaskKindInfo[];
};

const DIAGNOSTICS_RESULTS_KEY = "deeptutor.settings.diagnosticsResults.v1";

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

// The walk now runs down the settings navigator, which is on screen for
// every route, so each step points at the first row of a group rather than
// at a hub block that no longer exists. The overlay resolves the
// ``data-tour`` target after the page renders.
export const TOUR_STEPS: TourStep[] = [
  {
    target: "tour-status",
    route: "/settings/status",
    titleKey: "settingsTour.status.title",
    descKey: "settingsTour.status.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/appearance",
    titleKey: "settingsTour.appearance.title",
    descKey: "settingsTour.appearance.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/network",
    titleKey: "settingsTour.network.title",
    descKey: "settingsTour.network.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/llm",
    titleKey: "settingsTour.models.title",
    descKey: "settingsTour.models.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/knowledge",
    titleKey: "settingsTour.knowledge.title",
    descKey: "settingsTour.knowledge.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/starters",
    titleKey: "settingsTour.chat.title",
    descKey: "settingsTour.chat.desc",
  },
  {
    target: "tour-page-heading",
    route: "/settings/memory",
    titleKey: "settingsTour.memory.title",
    descKey: "settingsTour.memory.desc",
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────

export function cloneCatalog(catalog: Catalog): Catalog {
  return JSON.parse(JSON.stringify(catalog)) as Catalog;
}

/** TTS/STT share the catalog shape but configure audio providers. */
export function voiceService(service: ServiceName): boolean {
  return service === "tts" || service === "stt";
}

/** imagegen/videogen share the catalog shape but configure media generation. */
export function generationService(service: ServiceName): boolean {
  return service === "imagegen" || service === "videogen";
}

/** Services whose model entry should prefill from the provider's default model. */
function prefillsDefaultModel(service: ServiceName): boolean {
  return voiceService(service) || generationService(service);
}

export function defaultCatalog(): Catalog {
  return {
    version: 1,
    connections: [],
    services: {
      llm: { active_profile_id: null, active_model_id: null, profiles: [] },
      task: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      embedding: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      search: { active_profile_id: null, profiles: [] },
      tts: { active_profile_id: null, active_model_id: null, profiles: [] },
      stt: { active_profile_id: null, active_model_id: null, profiles: [] },
      imagegen: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      videogen: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
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

export function serviceConfigured(
  catalog: Catalog,
  serviceName: ServiceName,
): boolean {
  return serviceName === "search"
    ? Boolean(getActiveProfile(catalog, serviceName)?.provider)
    : Boolean(getActiveModel(catalog, serviceName)?.model);
}

export function currentDiagnosticsResult(
  catalog: Catalog,
  serviceName: ServiceName,
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>,
): DiagnosticsResult | null {
  const service = catalog.services[serviceName];
  const diagnostics = diagnosticsResults[serviceName];
  if (!diagnostics) return null;
  const profileId = service.active_profile_id ?? null;
  const modelId =
    serviceName === "search" ? null : (service.active_model_id ?? null);
  return diagnostics.profileId === profileId && diagnostics.modelId === modelId
    ? diagnostics
    : null;
}

export function serviceReadiness(
  catalog: Catalog,
  serviceName: ServiceName,
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>,
): ServiceReadiness {
  if (!serviceConfigured(catalog, serviceName)) return "not_configured";
  const diagnostics = currentDiagnosticsResult(
    catalog,
    serviceName,
    diagnosticsResults,
  );
  if (diagnostics?.state === "failed") return "failed";
  if (diagnostics?.state === "success") return "passed";
  return "untested";
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
  const prefix = language === "zh" ? "模型" : "Model ";
  const used = new Set(models.map((model) => model.name.trim()));
  let index = models.length + 1;
  while (used.has(`${prefix}${index}`)) {
    index += 1;
  }
  return `${prefix}${index}`;
}

function readStoredDiagnosticsResults(): Partial<
  Record<ServiceName, DiagnosticsResult>
> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(
      browserStorage.readRaw("session", DIAGNOSTICS_RESULTS_KEY) || "{}",
    ) as Partial<Record<ServiceName, DiagnosticsResult>>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

// ─── Context ───────────────────────────────────────────────────────────────

export interface SettingsExtension {
  dirty: boolean;
  save: () => Promise<void>;
  /**
   * The page's current editable state. Retained by the provider after the
   * page unmounts, so navigating away from a half-edited settings page no
   * longer throws the edit away, and stored in the draft so it survives a
   * reload. Pages that omit it keep the old (lossy) behaviour.
   */
  payload?: unknown;
}

export type SettingsContextValue = {
  // State
  catalog: Catalog;
  draft: Catalog;
  status: SystemStatus | null;
  providers: Record<ServiceName, ProviderOption[]>;
  catalogEditable: boolean | null;
  settingsLoading: boolean;
  settingsError: string | null;
  reloadSettings: () => Promise<void>;
  hasUnsavedChanges: boolean;
  theme: UiSettings["theme"];
  language: UiSettings["language"];
  responseLanguage: UiSettings["response_language"];
  codeBlockTheme: UiSettings["code_block_theme"];
  codeBlockShowLineNumbers: UiSettings["code_block_show_line_numbers"];
  codeBlockWrapLongLines: UiSettings["code_block_wrap_long_lines"];
  toast: string;
  setToast: (value: string) => void;

  // UI prefs
  updateTheme: (next: UiSettings["theme"]) => Promise<void>;
  updateLanguage: (next: UiSettings["language"]) => Promise<void>;
  updateResponseLanguage: (
    next: UiSettings["response_language"],
  ) => Promise<void>;
  updateCodeBlockTheme: (next: CodeBlockThemeId) => Promise<void>;
  updateCodeBlockShowLineNumbers: (next: boolean) => Promise<void>;
  updateCodeBlockWrapLongLines: (next: boolean) => Promise<void>;

  // Catalog mutation
  mutateCatalog: (mutator: (next: Catalog) => void) => void;
  addProfile: (service: ServiceName) => void;
  /** Omitting the id targets whatever is in use — the historical meaning. */
  removeActiveProfile: (service: ServiceName, profileId?: string) => void;
  addModel: (service: ServiceName, profileId?: string) => void;
  removeActiveModel: (
    service: ServiceName,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateProfileField: (
    service: ServiceName,
    field: keyof CatalogProfile,
    value: string,
    profileId?: string,
  ) => void;
  updateModelField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateModelBoolField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: boolean,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateContextWindowField: (
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateReasoningEffort: (
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  /** `null` clears the override so the built-in tables decide again. */
  updateModelCapability: (
    service: ServiceName,
    key: ModelCapabilityKey,
    value: boolean | null,
    profileId?: string,
    modelId?: string,
  ) => void;

  // Connections + task models
  connectionTargets: ConnectionTarget[];
  /** The calls DeepTutor makes on its own, in the order the backend lists them. */
  taskKinds: TaskKindInfo[];
  connectionTarget: (provider: string) => ConnectionTarget | null;
  addConnection: (input: {
    provider: string;
    name: string;
    api_key: string;
    base_url: string;
  }) => CatalogConnection;
  updateConnectionField: (
    id: string,
    field: keyof CatalogConnection,
    value: string,
  ) => void;
  removeConnection: (id: string) => void;
  unlinkProfile: (service: ServiceName, profileId: string) => void;
  linkConnectionToServices: (
    connection: Pick<
      CatalogConnection,
      "id" | "provider" | "name" | "api_key" | "base_url"
    >,
    requests: { service: ServiceName; model: string }[],
  ) => { created: ServiceName[]; activated: ServiceName[] };
  llmContextDetection: LlmContextWindowDetection | null;
  applyDetectedContextWindow: () => void;

  // Save / apply
  saving: boolean;
  applying: boolean;
  saveDraft: () => Promise<boolean>;
  applyCatalog: () => Promise<void>;
  /** Promote one model service without applying unrelated Settings drafts. */
  applyService: (service: ServiceName) => Promise<boolean>;
  saveRegistry: (edit: RegistryEdit) => Promise<boolean>;
  saveProvider: (service: ServiceName, profileId: string) => Promise<boolean>;
  discardDraft: () => Promise<void>;
  /** Stage a named Settings preset as a reviewable draft. */
  stagePreset: (presetId: string) => Promise<boolean>;
  /** A draft parked on the server, waiting to be applied. */
  storedDraft: StoredDraft | null;
  draftState: DraftState;
  /** Bumped when a draft is discarded so pages re-read from the server. */
  draftRevision: number;
  pendingExtensionPayload: (key: string) => unknown;

  // Sub-page extension hooks. Sub-routes (e.g. /settings#memory) that own
  // state outside the catalog register a "dirty + save" pair so the global
  // Apply button can flush them alongside the catalog. Re-register on every
  // render — the latest closure wins.
  registerExtension: (key: string, ext: SettingsExtension | null) => void;

  // Diagnostics
  modelTests: Record<string, ModelTestState>;
  logs: string;
  testRunning: ServiceName | null;
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>;
  embeddingCapabilities: EmbeddingCapabilities | null;
  runDetailedTest: (
    service: ServiceName,
    selection?: { profileId: string; modelId?: string },
  ) => Promise<void>;

  // Helpers
  embeddingDefaultDim: (binding?: string) => string;

  // Tour
  tourStepIndex: number;
  startTour: () => void;
  advanceTour: () => void;
  goBackTour: () => void;
  skipTour: () => void;

  // Which leaf is on screen inside a merged category page (models / chat /
  // agents). Null outside of one — the nav falls back to plain pathname
  // matching for every other route.
  activeSection: string | null;
  setActiveSection: (key: string | null) => void;
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
  // Code-block appearance lives in AppShellContext (the single source of truth,
  // also consumed by RichCodeBlock). Read the values from there and delegate
  // writes to its setters; this provider only adds backend persistence on top.
  const {
    codeBlockTheme,
    codeBlockShowLineNumbers,
    codeBlockWrapLongLines,
  } = useAppShell();

  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [theme, setTheme] = useState<UiSettings["theme"]>("snow");
  const [language, setLanguage] = useState<UiSettings["language"]>("en");
  const [responseLanguage, setResponseLanguage] =
    useState<UiSettings["response_language"]>("en");
  const [catalog, setCatalog] = useState<Catalog>(defaultCatalog());
  const [draft, setDraft] = useState<Catalog>(defaultCatalog());
  const [catalogEditable, setCatalogEditable] = useState<boolean | null>(null);
  const [providers, setProviders] = useState<
    Record<ServiceName, ProviderOption[]>
  >({
    llm: [],
    task: [],
    embedding: [],
    search: [],
    tts: [],
    stt: [],
    imagegen: [],
    videogen: [],
  });
  const [connectionTargets, setConnectionTargets] = useState<
    ConnectionTarget[]
  >([]);
  const [taskKinds, setTaskKinds] = useState<TaskKindInfo[]>([]);
  const [storedDraft, setStoredDraft] = useState<StoredDraft | null>(null);
  // Signature of the envelope as last written to the draft store.
  const [savedSignature, setSavedSignature] = useState<string | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  // Empty string is the "no diagnostics yet" sentinel; the editor renders
  // a localized placeholder when logs is falsy. Don't seed an English
  // literal here — older code did, then read it back via .startsWith.
  const [logs, setLogs] = useState<string>("");
  const [modelTests, setModelTests] = useState<Record<string, ModelTestState>>(
    {},
  );
  const testBusyRef = useRef(false);
  const [testRunning, setTestRunning] = useState<ServiceName | null>(null);
  const [diagnosticsResults, setDiagnosticsResults] = useState<
    Partial<Record<ServiceName, DiagnosticsResult>>
  >(() => readStoredDiagnosticsResults());
  const [llmContextDetection, setLlmContextDetection] =
    useState<LlmContextWindowDetection | null>(null);
  const [embeddingCapabilities, setEmbeddingCapabilities] =
    useState<EmbeddingCapabilities | null>(null);
  const [tourStepIndex, setTourStepIndex] = useState(-1);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  // Extensions register their latest dirty/save on each render. Keep the
  // derived dirty state explicit instead of using an indirect version counter.
  const extensionsRef = useRef<Map<string, SettingsExtension>>(new Map());
  // Pending edits from settings pages that keep state outside the catalog,
  // kept here rather than in the pages themselves. A page unmounts on every
  // navigation inside Settings; holding its unsaved payload at the provider
  // is what makes leaving the page non-destructive.
  const pendingRef = useRef<Map<string, unknown>>(new Map());
  // A signature of the pending payloads rather than just their keys: the
  // toolbar has to notice the second edit to the same field, not only the
  // first, or "Draft saved" would keep showing after further typing.
  const [pendingSignature, setPendingSignature] = useState("{}");
  const syncPendingKeys = useCallback(() => {
    const entries = Array.from(pendingRef.current.entries()).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    const next = JSON.stringify(Object.fromEntries(entries));
    setPendingSignature((current) => (current === next ? current : next));
  }, []);

  const registerExtension = useCallback(
    (key: string, ext: SettingsExtension | null) => {
      const map = extensionsRef.current;
      if (ext === null) {
        // Deregistration means "this page left the screen", never "discard
        // what was typed" — the pending payload deliberately outlives it.
        map.delete(key);
        return;
      }
      map.set(key, ext);
      if (ext.dirty) {
        if (ext.payload !== undefined) pendingRef.current.set(key, ext.payload);
      } else if (ext.payload != null) {
        // Clean *and* loaded means the user reverted, so the pending edit goes.
        // A null payload means the page is still fetching and has nothing to
        // say yet — dropping the pending edit there would delete it during the
        // very remount it is supposed to survive.
        pendingRef.current.delete(key);
      }
      syncPendingKeys();
    },
    [syncPendingKeys],
  );

  /** A payload this page left behind earlier in the session, if any. */
  const pendingExtensionPayload = useCallback(
    (key: string) => pendingRef.current.get(key),
    [],
  );

  const clearPending = useCallback(() => {
    pendingRef.current.clear();
    syncPendingKeys();
  }, [syncPendingKeys]);

  const [settingsError, setSettingsError] = useState<string | null>(null);

  // Single load step. Kept separate from the mount effect so a "Retry" action
  // can re-run it without remounting the provider.
  const loadSettings = useCallback(async () => {
    setSettingsError(null);
    let settingsLoaded = false;
    try {
      const settingsResponse = await apiFetch(apiUrl("/api/settings"));
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
      } else {
        setCatalogEditable(false);
      }
      setTheme(payload.ui.theme);
      setLanguage(payload.ui.language);
      const loadedResponseLanguage =
        payload.ui.response_language ?? payload.ui.language;
      setResponseLanguage(loadedResponseLanguage);
      // Reconcile the browser's copy with the server's. Without this the two
      // inherit differently and drift permanently: the server derives
      // `response_language` from `language` on every read, while the browser
      // inherits only when its own key is absent. Flipping the interface
      // language alone therefore left the server (and this page) showing 中文
      // while every turn still shipped the "en" the bootstrap had stamped —
      // the "I set Chinese and it answers in English" report.
      writeStoredLanguage(payload.ui.language);
      writeStoredResponseLanguage(loadedResponseLanguage);
      // Writes the backend-loaded values into app-shell storage and dispatches
      // the code-block settings event; AppShellContext (the single source) picks
      // them up, so no separate copy needs seeding here.
      syncLoadedCodeBlockSettingsToAppShell(payload.ui);
      if (payload.providers) setProviders(payload.providers);
      if (payload.connection_targets)
        setConnectionTargets(payload.connection_targets);
      if (payload.task_kinds) setTaskKinds(payload.task_kinds);

      // A draft parked in an earlier session takes over the editable copy —
      // otherwise "Save Draft" would look like it had done nothing at all.
      try {
        const draftResponse = await apiFetch(apiUrl("/api/settings/draft"));
        if (draftResponse.ok) {
          const stored = (await draftResponse.json()) as {
            draft: StoredDraft | null;
          };
          if (stored.draft) {
            setStoredDraft(stored.draft);
            if (stored.draft.catalog)
              setDraft(cloneCatalog(stored.draft.catalog));
            for (const [key, value] of Object.entries(
              stored.draft.extensions ?? {},
            )) {
              pendingRef.current.set(key, value);
            }
            syncPendingKeys();
            setSavedSignature(
              JSON.stringify({
                catalog: payload.catalog
                  ? (stored.draft.catalog ?? payload.catalog)
                  : null,
                extensions: JSON.stringify(
                  Object.fromEntries(
                    Array.from(pendingRef.current.entries()).sort(([a], [b]) =>
                      a < b ? -1 : a > b ? 1 : 0,
                    ),
                  ),
                ),
              }),
            );
            // Pages fetch their own state in parallel with this and may have
            // already read an empty pending map. Bumping the revision re-runs
            // their load effect now that the draft is actually here.
            setDraftRevision((value) => value + 1);
          }
        }
      } catch {
        // No draft is the normal case and a failed read must not block the
        // page; the live settings above are already in hand.
      }
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
      const statusResponse = await apiFetch(apiUrl("/api/system/status"));
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
  }, [syncPendingKeys, t]);

  // Load settings + status once on mount. Subsequent navigations between
  // settings sub-pages share this state via the layout-level provider.
  // Code-block switch hydration lives in AppShellContext (the single source),
  // so no separate post-mount re-read is needed here.
  //
  // Guarded because `loadSettings` closes over `t`, whose identity changes
  // once i18n resolves: without this the load ran a second time a moment
  // after mount and re-cloned `draft` from the server, silently discarding
  // anything edited in between. `reloadSettings` is the deliberate way to
  // re-read.
  const loadedOnce = useRef(false);
  useEffect(() => {
    if (!loadedOnce.current) {
      loadedOnce.current = true;
      loadSettings();
    }
  }, [loadSettings]);

  // A language change recreates loadSettings; it must not close an ongoing test.
  useEffect(() => () => eventSourceRef.current?.close(), []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    try {
      browserStorage.writeRaw(
        "session",
        DIAGNOSTICS_RESULTS_KEY,
        JSON.stringify(diagnosticsResults),
      );
    } catch {
      // Session storage is an enhancement for cross-route feedback only.
    }
  }, [diagnosticsResults]);

  // Preferences are drafts too. Browser-wide appearance/language changes only
  // when Apply succeeds, so Discard has no global side effects to undo.
  const liveUi = useMemo<UiSettings>(() => ({
    theme, language, response_language: responseLanguage,
    code_block_theme: codeBlockTheme,
    code_block_show_line_numbers: codeBlockShowLineNumbers,
    code_block_wrap_long_lines: codeBlockWrapLongLines,
  }), [theme, language, responseLanguage, codeBlockTheme, codeBlockShowLineNumbers, codeBlockWrapLongLines]);
  const applyUi = useCallback((ui: UiSettings) => {
    setTheme(ui.theme);
    setLanguage(ui.language);
    setResponseLanguage(ui.response_language);
    applyThemePreference(ui.theme);
    writeStoredLanguage(ui.language);
    writeStoredResponseLanguage(ui.response_language);
    syncLoadedCodeBlockSettingsToAppShell(ui);
  }, []);
  const stageUi = useCallback(async (patch: Partial<UiSettings>) => {
    const next = { ...liveUi, ...(pendingRef.current.get("ui") as Partial<UiSettings> | undefined), ...patch };
    registerExtension("ui", {
      dirty: JSON.stringify(next) !== JSON.stringify(liveUi),
      payload: next,
      save: async () => { await applyExtensionPayload("ui", next); applyUi(next); },
    });
  }, [liveUi, registerExtension, applyUi]);
  const updateTheme = useCallback(async (theme: UiSettings["theme"]) => stageUi({ theme }), [stageUi]);
  const updateLanguage = useCallback(async (language: UiSettings["language"]) => stageUi({ language }), [stageUi]);
  const updateResponseLanguage = useCallback(async (response_language: UiSettings["response_language"]) => stageUi({ response_language }), [stageUi]);
  const updateCodeBlockTheme = useCallback(async (code_block_theme: CodeBlockThemeId) => stageUi({ code_block_theme }), [stageUi]);
  const updateCodeBlockShowLineNumbers = useCallback(async (code_block_show_line_numbers: boolean) => stageUi({ code_block_show_line_numbers }), [stageUi]);
  const updateCodeBlockWrapLongLines = useCallback(async (code_block_wrap_long_lines: boolean) => stageUi({ code_block_wrap_long_lines }), [stageUi]);

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
        const providerOption = (providers[service] || []).find(
          (p) => p.value === providerKey,
        );
        const providerLabel =
          providerOption?.label ?? providerKey ?? "New Profile";
        const profile: CatalogProfile = {
          id: profileId,
          name: providerLabel,
          binding: defaultBinding,
          provider: defaultProvider,
          base_url: providerOption?.base_url ?? "",
          api_key: "",
          api_version: "",
          extra_headers: service === "search" ? undefined : {},
          wire_api: service === "llm" ? "auto" : undefined,
          api_format:
            service === "llm" || service === "task" ? "auto" : undefined,
          proxy: service === "search" ? "" : undefined,
          models: [],
        };
        if (service !== "search") {
          const modelId = `${service}-model-${Date.now()}`;
          const modelName = nextModelName([], language);
          profile.models.push({
            id: modelId,
            name: modelName,
            model: prefillsDefaultModel(service)
              ? (providerOption?.default_model ?? "")
              : "",
            ...(service === "embedding"
              ? {
                  dimension: embeddingDefaultDim(),
                  send_dimensions: true,
                }
              : {}),
            ...(service === "tts"
              ? {
                  voice: providerOption?.default_voice ?? "",
                  response_format: "",
                }
              : {}),
          });
          if (!target.active_profile_id) target.active_model_id = modelId;
        }
        target.profiles.push(profile);
        if (!target.active_profile_id) target.active_profile_id = profileId;
      });
    },
    [embeddingDefaultDim, language, mutateCatalog, providers],
  );

  const removeActiveProfile = useCallback(
    (service: ServiceName, profileId?: string) => {
      mutateCatalog((next) => {
        const target = next.services[service];
        const doomed = profileId ?? target.active_profile_id;
        target.profiles = target.profiles.filter(
          (profile) => profile.id !== doomed,
        );
        // Deleting a profile that was not in use leaves the selection alone.
        if (target.active_profile_id === doomed) {
          target.active_profile_id = target.profiles[0]?.id ?? null;
          if (service !== "search") {
            target.active_model_id =
              target.profiles[0]?.models?.[0]?.id ?? null;
          }
        }
      });
    },
    [mutateCatalog],
  );

  const addModel = useCallback(
    (service: ServiceName, profileId?: string) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile = profileId
          ? (target.profiles.find((item) => item.id === profileId) ?? null)
          : (target.profiles.find(
              (item) => item.id === target.active_profile_id,
            ) ?? null);
        if (!profile) return;
        const providerOption = (providers[service] || []).find(
          (p) => p.value === profile.binding,
        );
        const modelId = `${service}-model-${Date.now()}`;
        const modelName = nextModelName(profile.models, language);
        profile.models.push({
          id: modelId,
          name: modelName,
          model: prefillsDefaultModel(service)
            ? (providerOption?.default_model ?? "")
            : "",
          ...(service === "embedding"
            ? {
                dimension: embeddingDefaultDim(profile.binding),
                send_dimensions: true,
              }
            : {}),
          ...(service === "tts"
            ? {
                voice: providerOption?.default_voice ?? "",
                response_format: "",
              }
            : {}),
        });
        // Adding an option must not silently replace an existing selection.
        if (
          profile.id === target.active_profile_id &&
          !target.active_model_id
        ) {
          target.active_model_id = modelId;
        }
      });
    },
    [embeddingDefaultDim, language, mutateCatalog, providers],
  );

  // ─── Connections ─────────────────────────────────────────────────────────
  //
  // A connection holds the credential; linking creates one ordinary profile
  // per service that points back at it. The backend mirrors the credential
  // down on save, so everything downstream keeps reading self-contained
  // profiles — nothing about how a profile resolves changes by being linked.

  const connectionTarget = useCallback(
    (provider: string) =>
      connectionTargets.find((target) => target.provider === provider) ?? null,
    [connectionTargets],
  );

  const addConnection = useCallback(
    (input: {
      provider: string;
      name: string;
      api_key: string;
      base_url: string;
    }) => {
      const connection: CatalogConnection = {
        id: `conn-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name: input.name.trim() || input.provider,
        provider: input.provider,
        api_key: input.api_key,
        base_url: input.base_url.trim(),
        api_version: "",
        extra_headers: {},
      };
      mutateCatalog((next) => {
        next.connections = [...(next.connections ?? []), { ...connection }];
      });
      // Returned whole because the caller links services in the same click,
      // before the draft carrying it has been committed.
      return connection;
    },
    [mutateCatalog],
  );

  const updateConnectionField = useCallback(
    (id: string, field: keyof CatalogConnection, value: string) => {
      mutateCatalog((next) => {
        const connection = (next.connections ?? []).find(
          (item) => item.id === id,
        );
        if (connection) (connection as Record<string, unknown>)[field] = value;
      });
    },
    [mutateCatalog],
  );

  /**
   * Drop a connection. Profiles it fed keep the credentials already mirrored
   * into them — deleting the place a key was typed must not silently break
   * six working services.
   */
  const removeConnection = useCallback(
    (id: string) => {
      mutateCatalog((next) => {
        for (const service of CONNECTABLE_SERVICES) {
          for (const profile of next.services[service].profiles) {
            if (profile.connection_id === id)
              detachProfileConnection(next, service, profile);
          }
        }
        next.connections = (next.connections ?? []).filter(
          (item) => item.id !== id,
        );
      });
    },
    [mutateCatalog],
  );

  const unlinkProfile = useCallback(
    (service: ServiceName, profileId: string) => {
      mutateCatalog((next) => {
        const profile = next.services[service].profiles.find(
          (item) => item.id === profileId,
        );
        if (profile) detachProfileConnection(next, service, profile);
      });
    },
    [mutateCatalog],
  );

  /**
   * Create one linked profile per requested service.
   *
   * The plan — ids, which services get one, which of those become active — is
   * computed here rather than inside the catalog mutator: a mutator is a React
   * updater, so it runs during render (twice under StrictMode) and anything it
   * reports back would be both late and doubled.
   *
   * A new profile becomes the active one only for services that had none. A
   * user who already has a working LLM must not find their chat model swapped
   * out because they pasted a key for image generation, so what did and did
   * not become active is returned for the caller to say out loud.
   */
  const linkConnectionToServices = useCallback(
    (
      connection: Pick<
        CatalogConnection,
        "id" | "provider" | "name" | "api_key" | "base_url"
      >,
      requests: { service: ServiceName; model: string }[],
    ) => {
      const target = connectionTargets.find(
        (item) => item.provider === connection.provider,
      );
      const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
      const base = connection.base_url.trim().replace(/\/+$/, "");
      const plan = requests.flatMap((request, index) => {
        const spec = target?.services[request.service];
        if (!spec) return [];
        return [
          {
            service: request.service,
            spec,
            profileId: `${request.service}-profile-${stamp}${index}`,
            modelId: `${request.service}-model-${stamp}${index}`,
            model: request.model || spec.default_model || "",
            // Mirrored from the connection on save; seeded here so the draft
            // shows the same values the server will store.
            baseUrl: base
              ? request.service === "embedding"
                ? `${base}/embeddings`
                : base
              : spec.base_url,
            activate: draft.services[request.service].profiles.length === 0,
          },
        ];
      });

      mutateCatalog((next) => {
        for (const item of plan) {
          const bucket = next.services[item.service];
          bucket.profiles.push({
            id: item.profileId,
            name: connection.name,
            connection_id: connection.id,
            binding: item.spec.provider,
            base_url: item.baseUrl,
            api_key: connection.api_key,
            api_version: "",
            extra_headers: {},
            models: [
              {
                id: item.modelId,
                name: item.model || item.spec.provider,
                model: item.model,
                ...(item.service === "embedding"
                  ? {
                      dimension: item.spec.default_dim || "",
                      send_dimensions: true,
                    }
                  : {}),
                ...(item.service === "tts"
                  ? {
                      voice: item.spec.default_voice || "",
                      response_format: "",
                    }
                  : {}),
              },
            ],
          });
          if (item.activate) {
            bucket.active_profile_id = item.profileId;
            bucket.active_model_id = item.modelId;
          }
        }
      });

      return {
        created: plan.map((item) => item.service),
        activated: plan
          .filter((item) => item.activate)
          .map((item) => item.service),
      };
    },
    [connectionTargets, draft, mutateCatalog],
  );

  const removeActiveModel = useCallback(
    (service: ServiceName, profileId?: string, modelId?: string) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile = profileId
          ? (target.profiles.find((item) => item.id === profileId) ?? null)
          : (target.profiles.find(
              (item) => item.id === target.active_profile_id,
            ) ?? null);
        if (!profile) return;
        const doomed = modelId ?? target.active_model_id;
        profile.models = profile.models.filter((item) => item.id !== doomed);
        if (target.active_model_id === doomed) {
          target.active_model_id =
            profile.id === target.active_profile_id
              ? (profile.models[0]?.id ?? null)
              : target.active_model_id;
        }
      });
    },
    [mutateCatalog],
  );

  /**
   * Which profile/model an edit lands on.
   *
   * Everything here used to write to whatever was *active*, because selecting
   * a profile and putting it into use were the same act. The model pages now
   * let you open a profile without adopting it, so an edit has to name its
   * target — omitting it keeps the old meaning, so no existing caller changes.
   */
  const targetProfile = useCallback(
    (next: Catalog, service: ServiceName, profileId?: string) =>
      profileId
        ? (next.services[service].profiles.find(
            (item) => item.id === profileId,
          ) ?? null)
        : getActiveProfile(next, service),
    [],
  );

  const targetModel = useCallback(
    (
      next: Catalog,
      service: ServiceName,
      profileId?: string,
      modelId?: string,
    ) => {
      if (!profileId && !modelId) return getActiveModel(next, service);
      const profile = targetProfile(next, service, profileId);
      if (!profile) return null;
      return modelId
        ? (profile.models.find((item) => item.id === modelId) ?? null)
        : (profile.models[0] ?? null);
    },
    [targetProfile],
  );

  const updateProfileField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogProfile,
      value: string,
      profileId?: string,
    ) => {
      mutateCatalog((next) => {
        const profile = targetProfile(next, service, profileId);
        if (!profile) return;
        (profile[field] as string | undefined) = value;
      });
    },
    [mutateCatalog, targetProfile],
  );

  const updateModelField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogModel,
      value: string,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        (model[field] as string | undefined) = value;
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateModelBoolField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogModel,
      value: boolean,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        (model[field] as boolean | undefined) = value;
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateContextWindowField = useCallback(
    (value: string, profileId?: string, modelId?: string) => {
      const normalized = value.replace(/[^\d]/g, "");
      mutateCatalog((next) => {
        const model = targetModel(next, "llm", profileId, modelId);
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
    [mutateCatalog, targetModel],
  );

  const updateReasoningEffort = useCallback(
    (value: string, profileId?: string, modelId?: string) => {
      mutateCatalog((next) => {
        const model = targetModel(next, "llm", profileId, modelId);
        if (!model) return;
        setModelReasoningEffort(model, value);
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateModelCapability = useCallback(
    (
      service: ServiceName,
      key: ModelCapabilityKey,
      value: boolean | null,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        const capabilities = { ...(model.capabilities ?? {}) };
        if (value === null) delete capabilities[key];
        else capabilities[key] = value;
        if (Object.keys(capabilities).length === 0) delete model.capabilities;
        else model.capabilities = capabilities;
      });
    },
    [mutateCatalog, targetModel],
  );

  const applyDetectedContextWindow = useCallback(() => {
    if (!llmContextDetection || llmContextDetection.source === "default") return;
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
  /** The envelope the draft endpoint stores: catalog plus every pending page. */
  const draftEnvelope = useCallback(
    () => ({
      catalog: catalogEditable ? draft : null,
      extensions: Object.fromEntries(pendingRef.current.entries()),
    }),
    [catalogEditable, draft],
  );

  /**
   * Save Draft — write everything unsaved to the draft store and stop there.
   *
   * Nothing here reaches the files the runtime resolves against, which is the
   * entire difference from Apply. It covers the pages that keep state outside
   * the catalog too; previously this button only ever wrote the catalog and
   * reported success for edits it had not touched.
   */
  const saveDraft = useCallback(async () => {
    setSaving(true);
    const signature = envelopeSignatureRef.current;
    try {
      const response = await apiFetch(apiUrl("/api/settings/draft"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draftEnvelope()),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as {
        draft: StoredDraft | null;
      };
      setStoredDraft(payload.draft ?? null);
      setSavedSignature(signature);
      setToast(t("Draft saved — not applied yet"));
      return true;
    } catch (err) {
      setToast(
        t("Could not save the draft: {{message}}", {
          message: err instanceof Error ? err.message : String(err),
        }),
      );
      return false;
    } finally {
      setSaving(false);
    }
  }, [draftEnvelope, t]);

  /** Apply one model-service editor without promoting unrelated settings. */
  const applyService = useCallback(
    async (service: ServiceName): Promise<boolean> => {
      setApplying(true);
      try {
        const response = await apiFetch(apiUrl("/api/settings/apply/service"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            service,
            config: draft.services[service],
          }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as {
          catalog: Catalog;
          draft: StoredDraft | null;
        };
        const appliedService = cloneCatalog(payload.catalog).services[service];
        setCatalog(payload.catalog);
        setDraft((current) => {
          const next = cloneCatalog(current);
          if (
            JSON.stringify(current.services[service]) ===
            JSON.stringify(draft.services[service])
          )
            next.services[service] = appliedService;
          return next;
        });
        setStoredDraft(payload.draft ?? null);
        // The remaining in-memory edits may or may not match an older stored
        // draft. Mark them unsaved rather than claiming more durability than
        // this service-scoped action provided.
        setSavedSignature(null);
        invalidateLLMOptionsCache();
        try {
          const statusResponse = await apiFetch(apiUrl("/api/system/status"));
          if (statusResponse.ok) {
            setStatus((await statusResponse.json()) as SystemStatus);
          }
        } catch {
          // The catalog is already live. A status refresh failure should not
          // turn a successful apply into a failure or keep the dialog open.
        }
        setToast(t("Applied"));
        return true;
      } catch (err) {
        setToast(
          t("Could not apply: {{message}}", {
            message: err instanceof Error ? err.message : String(err),
          }),
        );
        return false;
      } finally {
        setApplying(false);
      }
    },
    [draft.services, t],
  );

  const saveRegistry = useCallback(
    async (edit: RegistryEdit): Promise<boolean> => {
      setApplying(true);
      try {
        const response = await apiFetch(
          apiUrl("/api/settings/apply/registry"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(edit),
          },
        );
        const payload = await response.json();
        if (!response.ok)
          throw new Error(
            typeof payload.detail === "string"
              ? payload.detail
              : `HTTP ${response.status}`,
          );
        setCatalog(payload.catalog);
        setDraft((current) =>
          reconcileRegistrySave(current, draft, payload.catalog, edit),
        );
        const normalized = reconcileRegistrySave(
          draft,
          draft,
          payload.catalog,
          edit,
        );
        setModelTests((current) => {
          const next = { ...current };
          for (const [key, result] of Object.entries(next)) {
            const [service, profileId, modelId] = JSON.parse(key) as [
              ServiceName,
              string,
              string | null,
            ];
            if (
              result.fingerprint ===
              modelTestFingerprint(draft, service, profileId, modelId)
            )
              next[key] = {
                ...result,
                fingerprint: modelTestFingerprint(
                  normalized,
                  service,
                  profileId,
                  modelId,
                ),
              };
          }
          return next;
        });
        setStoredDraft(payload.draft ?? null);
        setSavedSignature(null);
        invalidateLLMOptionsCache();
        setToast(t("Applied"));
        return true;
      } catch (error) {
        setToast(
          t("Could not apply: {{message}}", {
            message: error instanceof Error ? error.message : String(error),
          }),
        );
        return false;
      } finally {
        setApplying(false);
      }
    },
    [draft, t],
  );

  const saveProvider = useCallback(
    async (service: ServiceName, profileId: string): Promise<boolean> => {
      const profile = draft.services[service].profiles.find(
        (item) => item.id === profileId,
      );
      if (!profile) return false;
      const connection = draft.connections?.find(
        (item) => item.id === profile.connection_id,
      );
      const activate =
        draft.services[service].active_profile_id === profileId &&
        (service !== "task" ||
          !["inherit", "reference"].includes(
            draft.services.task.mode ?? "profiles",
          ));
      setApplying(true);
      try {
        const response = await apiFetch(
          apiUrl("/api/settings/apply/provider"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              service,
              profile,
              connection,
              activate,
              active_model_id: draft.services[service].active_model_id,
            }),
          },
        );
        const payload = await response.json();
        if (!response.ok)
          throw new Error(
            typeof payload.detail === "string"
              ? payload.detail
              : `HTTP ${response.status}`,
          );
        const live = payload.catalog as Catalog;
        setCatalog(live);
        setDraft((current) =>
          reconcileProviderSave(current, draft, live, service, profileId),
        );
        // Saving masks credentials and normalizes fields. Keep tests valid for
        // that exact submission; subsequent user edits still invalidate them.
        const normalized = reconcileProviderSave(
          draft,
          draft,
          live,
          service,
          profileId,
        );
        setModelTests((current) => {
          const next = { ...current };
          const modelIds =
            service === "search"
              ? [undefined]
              : profile.models.map((model) => model.id);
          for (const modelId of modelIds) {
            const key = modelTestKey(service, profileId, modelId);
            const result = next[key];
            if (
              result?.fingerprint ===
              modelTestFingerprint(draft, service, profileId, modelId)
            )
              next[key] = {
                ...result,
                fingerprint: modelTestFingerprint(
                  normalized,
                  service,
                  profileId,
                  modelId,
                ),
              };
          }
          return next;
        });
        setStoredDraft(payload.draft ?? null);
        setSavedSignature(null);
        invalidateLLMOptionsCache();
        setToast(t("Provider saved"));
        return true;
      } catch (error) {
        setToast(
          t("Could not apply: {{message}}", {
            message: error instanceof Error ? error.message : String(error),
          }),
        );
        return false;
      } finally {
        setApplying(false);
      }
    },
    [draft, t],
  );

  /** Apply — move everything into the live files and clear the draft. */
  const applyCatalog = useCallback(async () => {
    setApplying(true);
    try {
      if (catalogEditable) {
        for (const [service, bucket] of Object.entries(draft.services)) {
          for (const profile of bucket.profiles) {
            for (const model of profile.models) {
              const original = catalog.services[service as ServiceName].profiles
                .find((item) => item.id === profile.id)?.models.find((item) => item.id === model.id);
              if (JSON.stringify(original) !== JSON.stringify(model) && !model.model.trim()) {
                throw new Error(t("Enter a model ID before applying changes."));
              }
            }
          }
        }
      }

      // Park the current state server-side first so Apply promotes exactly
      // what is on screen, and so credentials typed into a draft never have
      // to round-trip through the browser as placeholders.
      const draftResponse = await apiFetch(apiUrl("/api/settings/draft"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draftEnvelope()),
      });

      if (!draftResponse.ok) throw new Error(`HTTP ${draftResponse.status}`);

      // Pages still on screen save themselves — they refresh their own local
      // state and surface their own errors. Everything else pending is
      // written straight to the endpoint that owns it.
      const mounted = extensionsRef.current;
      for (const [key, payload] of Array.from(pendingRef.current.entries())) {
        const ext = mounted.get(key);
        if (ext?.dirty) await ext.save();
        else await applyExtensionPayload(key, payload);
        if (key === "ui") applyUi(payload as UiSettings);
      }

      if (catalogEditable) {
        const response = await apiFetch(apiUrl("/api/settings/apply"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload.catalog)
          throw new Error("Missing catalog in apply response");
        setCatalog(payload.catalog);
        setDraft(cloneCatalog(payload.catalog));
        invalidateLLMOptionsCache();
        try {
          const statusResponse = await apiFetch(apiUrl("/api/system/status"));
          if (statusResponse.ok)
            setStatus((await statusResponse.json()) as SystemStatus);
        } catch {
          /* Applying succeeded; diagnostics can be retried independently. */
        }
      } else {
        const response = await apiFetch(apiUrl("/api/settings/draft"), {
          method: "DELETE",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      }
      clearPending();
      setStoredDraft(null);
      setSavedSignature(null);
      setDraftRevision((value) => value + 1);
      setToast(t("Applied"));
    } catch (err) {
      setToast(
        t("Could not apply: {{message}}", {
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    } finally {
      setApplying(false);
    }
  }, [catalog, draft, catalogEditable, clearPending, draftEnvelope, applyUi, t]);

  /** Stage a named preset over the current draft without applying anything. */
  const stagePreset = useCallback(
    async (presetId: string): Promise<boolean> => {
      setSaving(true);
      try {
        const response = await apiFetch(
          apiUrl(`/api/settings/presets/${presetId}/draft`),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draftEnvelope()),
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as {
          draft: StoredDraft | null;
        };
        const stored = payload.draft;
        const pending = new Map(
          Object.entries(stored?.extensions ?? {}),
        );

        pendingRef.current.clear();
        for (const [key, value] of pending.entries()) {
          pendingRef.current.set(key, value);
        }
        syncPendingKeys();
        if (stored?.catalog) setDraft(cloneCatalog(stored.catalog));
        setStoredDraft(stored);
        // The server has the exact staged envelope; avoid the toolbar calling
        // it unsaved while the new draft signature is still propagating.
        setSavedSignature(
          JSON.stringify({
            catalog: catalogEditable ? (stored?.catalog ?? draft) : null,
            extensions: JSON.stringify(Object.fromEntries(pending.entries())),
          }),
        );
        setDraftRevision((value) => value + 1);
        setToast(t("Preset loaded as a draft — review before applying"));
        return true;
      } catch (err) {
        setToast(
          t("Could not load the preset: {{message}}", {
            message: err instanceof Error ? err.message : String(err),
          }),
        );
        return false;
      } finally {
        setSaving(false);
      }
    },
    [catalogEditable, draft, draftEnvelope, syncPendingKeys, t],
  );

  /** Throw the draft away and go back to what is actually live. */
  const discardDraft = useCallback(async () => {
    setApplying(true);
    try {
      const response = await apiFetch(apiUrl("/api/settings/draft"), {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      clearPending();
      setStoredDraft(null);
      setSavedSignature(null);
      setDraft(cloneCatalog(catalog));
      setToast(t("Draft discarded"));
      // Pages holding their own copy of a discarded payload have to re-read.
      setDraftRevision((value) => value + 1);
    } catch (err) {
      setToast(
        t("Could not discard the draft: {{message}}", {
          message: err instanceof Error ? err.message : String(err),
        }),
      );
    } finally {
      setApplying(false);
    }
  }, [catalog, clearPending, t]);

  // ── Diagnostics ─────────────────────────────────────────────────────────
  // Reset capability snapshot when switching embedding profile/model so a
  // stale "Detected: Xd" hint doesn't bleed across profiles.
  useEffect(() => {
    setEmbeddingCapabilities(null);
  }, [
    draft.services.embedding.active_profile_id,
    draft.services.embedding.active_model_id,
  ]);

  const llmActiveProfileId = draft.services.llm.active_profile_id;
  const llmActiveModelId = draft.services.llm.active_model_id;
  useEffect(() => {
    setLlmContextDetection((current) => {
      if (!current) return null;
      if (
        current.profileId === llmActiveProfileId &&
        current.modelId === llmActiveModelId
      ) {
        return current;
      }
      return null;
    });
  }, [llmActiveProfileId, llmActiveModelId]);

  const runDetailedTest = useCallback(
    async (
      service: ServiceName,
      selection?: { profileId: string; modelId?: string },
    ) => {
      if (!catalogEditable || testBusyRef.current) return;
      const diagnosticCatalog = cloneCatalog(draft);
      const target = diagnosticCatalog.services[service];
      const runProfileId = selection?.profileId ?? target.active_profile_id;
      const runModelId =
        service === "search"
          ? null
          : (selection?.modelId ?? target.active_model_id);
      const profile = target.profiles.find((item) => item.id === runProfileId);
      if (
        !profile ||
        (service !== "search" &&
          !profile.models.some(
            (item) => item.id === runModelId && item.model.trim(),
          ))
      )
        return;
      if (service === "task") target.mode = "profiles";
      target.active_profile_id = runProfileId;
      if (service !== "search") target.active_model_id = runModelId;
      const key = modelTestKey(service, profile.id, runModelId);
      const fingerprint = modelTestFingerprint(
        draft,
        service,
        profile.id,
        runModelId,
      );
      let finished = false;
      testBusyRef.current = true;
      setTestRunning(service);
      setLogs("");
      setModelTests((current) => ({
        ...current,
        [key]: {
          state: "running",
          fingerprint,
          logs: "",
          message: t("Testing model…"),
        },
      }));
      const update = (patch: Partial<ModelTestState>) =>
        setModelTests((current) => ({
          ...current,
          [key]: { ...current[key], ...patch },
        }));
      const finish = (state: "success" | "failed", message: string) => {
        if (finished) return;
        finished = true;
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        testBusyRef.current = false;
        setTestRunning(null);
        update({ state, message });
        setDiagnosticsResults((current) => ({
          ...current,
          [service]: {
            state,
            message,
            profileId: profile.id,
            modelId: runModelId ?? null,
          },
        }));
      };
      try {
        const response = await apiFetch(
          apiUrl(`/api/settings/tests/${service}/start`),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ catalog: diagnosticCatalog }),
          },
        );
        const payload = await response.json();
        if (!response.ok || !payload.run_id)
          throw new Error(
            typeof payload.detail === "string"
              ? payload.detail
              : t("Could not start diagnostics."),
          );
        const source = new EventSource(
          apiUrl(`/api/settings/tests/${service}/${payload.run_id}/events`),
          { withCredentials: true },
        );
        eventSourceRef.current = source;
        source.onmessage = (event) => {
          if (finished) return;
          try {
            const entry = JSON.parse(event.data);
            const line = `[${entry.type}] ${entry.message || ""}\n`;
            setLogs((current) => current + line);
            setModelTests((current) => ({
              ...current,
              [key]: {
                ...current[key],
                logs: current[key].logs + line,
                message: entry.message || current[key].message,
              },
            }));
            if (entry.type === "response" && entry.snippet)
              update({ response: entry.snippet });
            if (
              entry.type === "context_window" &&
              Number(entry.context_window) > 0
            ) {
              const context = {
                value: Number(entry.context_window),
                source: entry.source || "metadata",
                detail: entry.detail,
                detectedAt: entry.detected_at,
              };
              update({ context });
              if (service === "llm")
                setLlmContextDetection({
                  profileId: profile.id,
                  modelId: runModelId ?? null,
                  contextWindow: context.value,
                  source: context.source,
                  detail: context.detail,
                  detectedAt: context.detectedAt,
                });
            }
            if (entry.type === "capabilities") {
              update({
                dimension: entry.detected_dim,
                supportedDimensions: entry.supported_dimensions,
              });
              setEmbeddingCapabilities(entry);
            }
            // A probe never replaces the catalog or the user's in-progress edits.
            // Metadata is offered to the addressed model for explicit adoption.
            if (entry.type === "completed") finish("success", entry.message);
            if (entry.type === "failed") finish("failed", entry.message);
          } catch {
            finish("failed", t("Could not read the model test result."));
          }
        };
        source.onerror = () =>
          finish("failed", t("Diagnostics stream disconnected."));
      } catch (error) {
        finish(
          "failed",
          error instanceof Error
            ? error.message
            : t("Could not start diagnostics."),
        );
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
  // What the current screen state would be persisted as. Compared against the
  // last thing actually written so the toolbar can tell "not saved anywhere"
  // apart from "saved as a draft, not applied".
  const envelopeSignature = useMemo(
    () =>
      JSON.stringify({
        catalog: catalogEditable ? draft : null,
        extensions: pendingSignature,
      }),
    [catalogEditable, draft, pendingSignature],
  );

  const differsFromLive = useMemo(
    () =>
      pendingSignature !== "{}" ||
      (catalogEditable === true &&
        JSON.stringify(catalog) !== JSON.stringify(draft)),
    [catalog, catalogEditable, draft, pendingSignature],
  );

  const envelopeSignatureRef = useRef(envelopeSignature);
  envelopeSignatureRef.current = envelopeSignature;

  const changedStoredDraft = storedDraft !== null && savedSignature !== null && envelopeSignature !== savedSignature;
  const draftState: DraftState = !differsFromLive && !changedStoredDraft
    ? "clean"
    : envelopeSignature === savedSignature
      ? "saved"
      : "unsaved";

  const hasUnsavedChanges = draftState === "unsaved";

  // Moving between settings pages keeps unsaved edits (they live on the
  // provider), but closing or reloading the tab cannot — that is the moment
  // the work would disappear, so warn there. Only for edits with nowhere to
  // fall back to: once saved as a draft the server already has them.
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsavedChanges]);

  const settingsLoading = catalogEditable === null;

  const editedUi = useMemo(() => ({ ...liveUi, ...(JSON.parse(pendingSignature).ui as Partial<UiSettings> | undefined) }), [liveUi, pendingSignature]);
  const value = useMemo<SettingsContextValue>(
    () => ({
      catalog,
      draft,
      status,
      providers,
      catalogEditable,
      settingsLoading,
      settingsError,
      reloadSettings: loadSettings,
      hasUnsavedChanges,
      theme: editedUi.theme,
      language: editedUi.language,
      responseLanguage: editedUi.response_language,
      codeBlockTheme: editedUi.code_block_theme,
      codeBlockShowLineNumbers: editedUi.code_block_show_line_numbers,
      codeBlockWrapLongLines: editedUi.code_block_wrap_long_lines,
      toast,
      setToast,
      updateTheme,
      updateLanguage,
      updateResponseLanguage,
      updateCodeBlockTheme,
      updateCodeBlockShowLineNumbers,
      updateCodeBlockWrapLongLines,
      mutateCatalog,
      addProfile,
      removeActiveProfile,
      addModel,
      removeActiveModel,
      updateProfileField,
      updateModelField,
      updateModelBoolField,
      updateContextWindowField,
      updateReasoningEffort,
      updateModelCapability,
      connectionTargets,
      taskKinds,
      connectionTarget,
      addConnection,
      updateConnectionField,
      removeConnection,
      unlinkProfile,
      linkConnectionToServices,
      llmContextDetection,
      applyDetectedContextWindow,
      saving,
      applying,
      saveDraft,
      applyCatalog,
      saveProvider,
      saveRegistry,
      applyService,
      discardDraft,
      stagePreset,
      storedDraft,
      draftState,
      draftRevision,
      pendingExtensionPayload,
      registerExtension,
      logs,
      testRunning,
      modelTests,
      diagnosticsResults,
      embeddingCapabilities,
      runDetailedTest,
      embeddingDefaultDim,
      tourStepIndex,
      startTour,
      advanceTour,
      goBackTour,
      skipTour,
      activeSection,
      setActiveSection,
    }),
    [
      editedUi,
      activeSection,
      addModel,
      addProfile,
      applyDetectedContextWindow,
      applyCatalog,
      saveProvider,
      saveRegistry,
      applyService,
      applying,
      stagePreset,
      draftState,
      storedDraft,
      draftRevision,
      pendingExtensionPayload,
      discardDraft,
      catalog,
      catalogEditable,
      modelTests,
      diagnosticsResults,
      draft,
      embeddingCapabilities,
      embeddingDefaultDim,
      hasUnsavedChanges,
      llmContextDetection,
      logs,
      mutateCatalog,
      connectionTargets,
      taskKinds,
      connectionTarget,
      addConnection,
      updateConnectionField,
      removeConnection,
      unlinkProfile,
      linkConnectionToServices,
      providers,
      registerExtension,
      removeActiveModel,
      removeActiveProfile,
      runDetailedTest,
      saveDraft,
      saving,
      setActiveSection,
      settingsError,
      loadSettings,
      settingsLoading,
      skipTour,
      startTour,
      advanceTour,
      goBackTour,
      status,
      testRunning,
      toast,
      tourStepIndex,
      updateCodeBlockShowLineNumbers,
      updateCodeBlockTheme,
      updateCodeBlockWrapLongLines,
      updateContextWindowField,
      updateReasoningEffort,
      updateModelCapability,
      updateLanguage,
      updateResponseLanguage,
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
