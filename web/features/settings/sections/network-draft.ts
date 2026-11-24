/**
 * Draft helpers for the Network settings page.
 *
 * Kept out of `NetworkSettingsSection` so the mapping between the
 * `GET /api/settings/network` payload and the form state is testable without a
 * DOM. Nothing here interprets the SSRF policy itself — that lives on the
 * server (`deeptutor/services/net_policy.py`); this module only decides what
 * the form shows and what it posts back.
 */

export type NetworkSettings = {
  backend_port: number;
  frontend_port: number;
  public_api_base: string;
  cors_origins: string[];
  ssrf_protection_enabled: boolean;
  network_synthetic_ranges: string[];
};

export type EffectiveNetworkSettings = {
  backend_url: string;
  frontend_url: string;
  browser_api_base: string;
  api_base_source: string;
  cors_mode: "explicit" | "permissive";
  cors_origins: string[];
  allow_remote_http_origins: boolean;
  ssrf_protection_enabled: boolean;
  network_synthetic_ranges: string[];
  /** A `DEEPTUTOR_SSRF_*` deployment variable wins over `system.json`. */
  ssrf_policy_env_override: boolean;
};

export type NetworkSettingsPayload = {
  settings: NetworkSettings;
  effective: EffectiveNetworkSettings;
  auth: {
    enabled: boolean;
    cookie_secure: boolean;
    cookie_samesite: string;
    cross_site_cookie_ready: boolean;
  };
  restart_required: boolean;
};

/** Comma, semicolon and newline separated values, trimmed and non-empty. */
export function splitNetworkList(value: string): string[] {
  return value
    .split(/[,;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function normalizeNetworkDraft(
  payload: NetworkSettingsPayload,
): NetworkSettings {
  return {
    backend_port: payload.settings.backend_port,
    frontend_port: payload.settings.frontend_port,
    public_api_base: payload.settings.public_api_base || "",
    cors_origins: payload.settings.cors_origins || [],
    // An older backend does not send these; strict and undeclared is what the
    // server does in that case, so mirror it instead of inventing a policy.
    ssrf_protection_enabled: payload.settings.ssrf_protection_enabled !== false,
    network_synthetic_ranges: payload.settings.network_synthetic_ranges || [],
  };
}

/** What the page posts: the textareas are authoritative for both lists. */
export function networkDraftPayload(
  draft: NetworkSettings,
  corsText: string,
  rangesText: string,
): NetworkSettings {
  return {
    ...draft,
    cors_origins: splitNetworkList(corsText),
    network_synthetic_ranges: splitNetworkList(rangesText),
  };
}

export function isNetworkDraftDirty(
  payload: NetworkSettingsPayload,
  draft: NetworkSettings,
  corsText: string,
  rangesText: string,
): boolean {
  const current = normalizeNetworkDraft(payload);
  return (
    current.backend_port !== draft.backend_port ||
    current.frontend_port !== draft.frontend_port ||
    current.public_api_base !== draft.public_api_base ||
    current.ssrf_protection_enabled !== draft.ssrf_protection_enabled ||
    JSON.stringify(current.cors_origins) !==
      JSON.stringify(splitNetworkList(corsText)) ||
    JSON.stringify(current.network_synthetic_ranges) !==
      JSON.stringify(splitNetworkList(rangesText))
  );
}

/** The toggle reads "allow private targets", the setting records the guard. */
export function ssrfProtectionFromToggle(allowPrivate: boolean): boolean {
  return !allowPrivate;
}

export function allowPrivateTargets(draft: NetworkSettings): boolean {
  return draft.ssrf_protection_enabled === false;
}
