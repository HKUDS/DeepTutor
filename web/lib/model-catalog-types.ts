/** Shared catalog schema. Provider references extend legacy profiles without re-keying them. */
export type ProviderRef = {
  connection_id?: string;
  service?: ServiceName;
  profile_id?: string;
  binding?: string;
  default_base_url?: string;
};
export type Discovery = {
  status: string;
  models: { id: string }[];
  capabilities?: { category: string; evidence: string }[];
  checked_at?: string;
};
export type ServiceName =
  | "llm"
  /** Same shape as `llm`; stands in for it on the calls DeepTutor makes itself. */
  | "task"
  | "embedding"
  | "search"
  | "tts"
  | "stt"
  | "imagegen"
  | "videogen";

/**
 * What the user declared about a model, overriding the built-in capability
 * tables. A missing key means "let DeepTutor decide".
 */
export type ModelCapabilities = {
  tools?: boolean;
  vision?: boolean;
  json_output?: boolean;
  reasoning?: boolean;
};
export type ModelCapabilityKey = keyof ModelCapabilities;

export type ApiFormat =
  "auto" | "openai_chat" | "openai_responses" | "anthropic";

export type CatalogModel = {
  user_name?: string;
  provider_ref?: ProviderRef;
  id: string;
  name: string;
  model: string;
  managed_by?: string;
  capabilities?: ModelCapabilities;
  dimension?: string;
  send_dimensions?: boolean;
  supported_dimensions?: string;
  context_window?: string;
  context_window_tokens?: string | number;
  context_window_source?: string;
  context_window_detected_at?: string;
  reasoning_effort?: string;
  codex_supported_reasoning_levels?: string[];
  // Voice (TTS): free-form provider/model-specific voice string, e.g.
  // "alloy", "autumn", "model:voice". `response_format` is the TTS output
  // codec (mp3/wav/...) and is reused by imagegen ("url"/"b64_json").
  // `language` is an optional STT hint.
  voice?: string;
  speed?: string;
  sample_rate?: string;
  instructions?: string;
  resource_id?: string;
  response_format?: string;
  language?: string;
  // Image generation: pixel size (e.g. "1024x1024"), quality, and style.
  size?: string;
  quality?: string;
  style?: string;
  // Video generation: aspect ratio (e.g. "16:9"), duration (seconds), resolution.
  aspect_ratio?: string;
  duration?: string;
  resolution?: string;
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
  user_name?: string;
  provider_ref?: ProviderRef;
  provider_only?: boolean;
  display_name?: string;
  discovery?: Discovery;
  id: string;
  name: string;
  managed_by?: string;
  codex_account_binding?: string;
  read_only?: boolean;
  binding?: string;
  provider?: string;
  base_url: string;
  api_key: string;
  api_version: string;
  app_id?: string;
  extra_headers?: Record<string, string> | string;
  wire_api?: "auto" | "responses" | "chat_completions";
  /** The protocol this endpoint speaks; the backend derives wire_api from it. */
  api_format?: ApiFormat;
  proxy?: string;
  max_results?: number;
  /** Set when this profile's credentials come from a catalog connection. */
  connection_id?: string;
  models: CatalogModel[];
};

/** How a task model choice points at a model. */
export type TaskChoiceMode = "inherit" | "reference" | "profiles";

/**
 * One background task's own model, keyed by the backend's `TaskKind`.
 *
 * A task absent from `overrides` follows the global task model. Following the
 * global choice is deliberately the *absence* of a row rather than a fourth
 * mode, so a default has no second place to disagree with itself.
 */
export type CatalogTaskOverride = {
  mode: TaskChoiceMode;
  selection?: { profile_id: string; model_id: string };
  active_profile_id?: string;
  active_model_id?: string;
};

export type CatalogService = {
  mode?: TaskChoiceMode;
  selection?: { profile_id: string; model_id: string };
  active_profile_id: string | null;
  active_model_id?: string | null;
  /** `task` only: the tasks that run on something other than the global choice. */
  overrides?: Record<string, CatalogTaskOverride>;
  profiles: CatalogProfile[];
};

/**
 * One call DeepTutor makes on its own, as the backend enumerates them.
 *
 * The list ships with the settings payload rather than being restated here:
 * every entry comes from a call site that names its `TaskKind`, so this page
 * cannot offer a task DeepTutor no longer runs, or miss one it just gained.
 */
export type TaskKindInfo = { id: string; group: string };

/**
 * One vendor credential, typed once and mirrored into every service profile
 * that links to it. The backend does the mirroring on save, so a linked
 * profile still stores its own resolved credentials — linking changes where
 * they were typed, not how they resolve.
 */
export type CatalogConnection = {
  source_service?: ServiceName;
  discovery?: Discovery;
  api_format?: ApiFormat;
  wire_api?: "auto" | "responses" | "chat_completions";
  proxy?: string;
  id: string;
  name: string;
  provider: string;
  api_key: string;
  /** Optional endpoint override; blank means each service's own default. */
  base_url: string;
  api_version: string;
  app_id?: string;
  extra_headers?: Record<string, string> | string;
};

/** Per-service prefills a connection's provider can supply, from the backend. */
export type ConnectionTargetService = {
  provider: string;
  base_url: string;
  default_model: string;
  default_dim?: string;
  default_voice?: string;
};

export type ConnectionTarget = {
  provider: string;
  label: string;
  default_base_url: string;
  services: Partial<Record<ServiceName, ConnectionTargetService>>;
};

/** Services a connection can supply, in the order the UI lists them. */
export const CONNECTABLE_SERVICES: ServiceName[] = [
  "llm",
  "task",
  "embedding",
  "tts",
  "stt",
  "imagegen",
  "videogen",
];

export type Catalog = {
  version: number;
  connections?: CatalogConnection[];
  services: {
    llm: CatalogService;
    task: CatalogService;
    embedding: CatalogService;
    search: CatalogService;
    tts: CatalogService;
    stt: CatalogService;
    imagegen: CatalogService;
    videogen: CatalogService;
  };
};

export type VoiceChoice = { id: string; label: string; languages?: string[] };
export type VoiceModelOption = {
  id: string;
  label: string;
  voices: VoiceChoice[];
  languages: VoiceChoice[];
  formats: string[];
  language_note?: string;
  max_input_chars?: number;
  speed?: { min: number; max: number; step: number };
  sample_rates?: number[];
  instructions?: boolean;
};
export type VoiceOptions = {
  models: VoiceModelOption[];
  fallback: VoiceModelOption;
  docs_url: string;
};

export type ProviderOption = {
  voice_options?: VoiceOptions;
  value: string;
  label: string;
  base_url?: string;
  default_dim?: string;
  default_model?: string;
  default_voice?: string;
  auth_mode?: "api_key" | "oauth";
  supports_wire_api_selection?: boolean;
  // LLM-shaped services: which API formats a profile may pick, the one a new
  // profile starts on, and the vendor endpoint per format where it differs.
  api_formats?: string[];
  default_api_format?: string;
  base_urls?: Record<string, string>;
  // Search providers only, from the backend SEARCH_PROVIDERS spec table:
  // which connection fields the provider consumes, whether missing ones fall
  // back to a free provider or fail hard, and whether it is still offered.
  requires_api_key?: boolean;
  requires_base_url?: boolean;
  soft_fallback?: boolean;
  status?: "supported" | "deprecated" | "legacy";
};
