// Which connection fields a web-search provider actually uses.
//
// The answer comes from the backend spec table
// (`SEARCH_PROVIDERS` in `deeptutor/services/config/provider_runtime.py`),
// served per provider by `_provider_choices` in
// `deeptutor/api/routers/settings.py`. There is deliberately no provider table
// here — a second copy is how the web app ended up flagging Serper as
// deprecated while the backend supported it.
//
// Until the choices load (and for a custom or retired provider name that has no
// entry), every field is shown: better an extra control than a hidden one the
// provider actually needs.

import type { ProviderOption } from "./SettingsContext";

export type SearchProviderFieldSpec = {
  /** Provider authenticates with an API key. */
  apiKey: boolean;
  /** Provider is configured with a Base URL. */
  baseUrl: boolean;
  /** The Base URL is mandatory — the provider cannot work without it. */
  baseUrlRequired: boolean;
};

const ALL_FIELDS: SearchProviderFieldSpec = {
  apiKey: true,
  baseUrl: true,
  baseUrlRequired: false,
};

/**
 * Resolve which connection fields to show for a search provider, given the
 * backend option describing it. Unknown, custom, retired, or not-yet-loaded
 * providers fall back to showing every field.
 */
export function searchProviderFields(
  provider: string | null | undefined,
  option?: ProviderOption | null,
): SearchProviderFieldSpec {
  const key = (provider ?? "").trim().toLowerCase();
  if (!key) return ALL_FIELDS;
  if (!option || option.status === "deprecated") return ALL_FIELDS;
  if (option.requires_api_key === undefined) return ALL_FIELDS;
  const baseUrl = Boolean(option.requires_base_url);
  return {
    apiKey: Boolean(option.requires_api_key),
    baseUrl,
    baseUrlRequired: baseUrl,
  };
}
