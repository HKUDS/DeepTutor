import type {
  CatalogProfile,
  ProviderOption,
  ServiceName,
} from "./SettingsContext";

/** The tag the backend stamps on the profile its Codex OAuth service owns. */
export const CODEX_MANAGED_BY = "openai_codex_oauth";

/** Profiles written by the Codex OAuth service are read-only in the settings form. */
export function isManagedCodexProfile(
  profile: Pick<CatalogProfile, "managed_by"> | null | undefined,
): boolean {
  return profile?.managed_by === CODEX_MANAGED_BY;
}

/**
 * Whether a profile authenticates through Codex OAuth instead of typed credentials.
 *
 * A managed profile qualifies even before the provider list has loaded, so a
 * reload can never briefly render API-key fields over an OAuth-only profile.
 */
export function isCodexOAuthProfile(
  service: ServiceName,
  providerValue: string,
  providerOption: Pick<ProviderOption, "auth_mode"> | undefined,
  profile: Pick<CatalogProfile, "managed_by"> | null | undefined,
): boolean {
  return (
    service === "llm" &&
    providerValue === "openai_codex" &&
    (providerOption?.auth_mode === "oauth" || isManagedCodexProfile(profile))
  );
}
