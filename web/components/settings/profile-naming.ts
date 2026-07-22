// Auto-naming for connection profiles.
//
// A new profile is created already named after its provider (see `addProfile`
// in SettingsContext). As long as the user hasn't typed a custom name, we want
// the name to keep tracking the provider when they switch it — so a profile
// created as "Brave" becomes "Jina" when the provider changes to Jina, but a
// profile the user renamed to "My search" is left untouched.
//
// The heuristic is deliberately stateless (no extra persisted field): the name
// is considered "auto" when it is empty or still equals the previous provider's
// label. Once it diverges, it is treated as user-owned and never overwritten.

export function nextProfileName(
  currentName: string,
  previousProviderLabel: string,
  nextProviderLabel: string,
): string {
  // Never overwrite with an empty label (e.g. "Select provider…").
  if (!nextProviderLabel) return currentName;
  const trimmed = (currentName ?? "").trim();
  if (trimmed === "" || trimmed === (previousProviderLabel ?? "").trim()) {
    return nextProviderLabel;
  }
  return currentName;
}
