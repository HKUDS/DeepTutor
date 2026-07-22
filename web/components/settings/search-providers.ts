// Which connection fields a web-search provider actually uses.
//
// This mirrors the backend resolver in
// `deeptutor/services/config/provider_runtime.py`
// (`resolve_search_runtime_config`): brave/tavily/jina/perplexity/serper
// authenticate with an API key, searxng is configured by its instance Base
// URL, and duckduckgo/none need no connection details at all. Every search
// provider ships an empty `base_url` from the settings API
// (`_provider_choices` in `deeptutor/api/routers/settings.py`), so the Base
// URL only ever carries a value for searxng.
//
// Keep this table in sync with SUPPORTED_SEARCH_PROVIDERS on the backend.

export type SearchProviderFieldSpec = {
  /** Provider authenticates with an API key. */
  apiKey: boolean;
  /** Provider is configured with a Base URL. */
  baseUrl: boolean;
  /** The Base URL is mandatory — the provider cannot work without it. */
  baseUrlRequired: boolean;
};

const KEY_ONLY: SearchProviderFieldSpec = {
  apiKey: true,
  baseUrl: false,
  baseUrlRequired: false,
};

const NO_CREDENTIALS: SearchProviderFieldSpec = {
  apiKey: false,
  baseUrl: false,
  baseUrlRequired: false,
};

const BASE_URL_ONLY: SearchProviderFieldSpec = {
  apiKey: false,
  baseUrl: true,
  baseUrlRequired: true,
};

// Providers we don't model (a custom/unknown value, the deprecated
// exa/baidu/openrouter set, or an empty selection): show every field so we
// never hide a control the provider might actually need.
const UNKNOWN: SearchProviderFieldSpec = {
  apiKey: true,
  baseUrl: true,
  baseUrlRequired: false,
};

const SEARCH_PROVIDER_FIELDS: Record<string, SearchProviderFieldSpec> = {
  none: NO_CREDENTIALS,
  duckduckgo: NO_CREDENTIALS,
  searxng: BASE_URL_ONLY,
  brave: KEY_ONLY,
  tavily: KEY_ONLY,
  jina: KEY_ONLY,
  perplexity: KEY_ONLY,
  serper: KEY_ONLY,
};

/**
 * Resolve which connection fields to show for a search provider. Unknown,
 * custom, or empty provider names fall back to showing every field.
 */
export function searchProviderFields(
  provider: string | null | undefined,
): SearchProviderFieldSpec {
  const key = (provider ?? "").trim().toLowerCase();
  if (!key) return UNKNOWN;
  return SEARCH_PROVIDER_FIELDS[key] ?? UNKNOWN;
}
