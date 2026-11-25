/**
 * Pure helpers for the fallback-chain editor (#2693 P3).
 *
 * The chain is one ordered list on `services.llm`, pointing at profiles and
 * models that already exist in the catalog — the editor never creates them.
 */

export type FallbackEntry = { profile_id: string; model_id: string };

export type FallbackChoice = {
  /** `profile_id` used by the payload. */
  profileId: string;
  /** `models[].id` used by the payload. */
  modelId: string;
  /** Human label shown in the selects. */
  label: string;
};

type ProfileLike = {
  id: string;
  name?: string;
  display_name?: string;
  models?: { id: string; name?: string; model?: string }[];
};

/** Every selectable (profile, model) pair in one flat, ordered list. */
export function fallbackChoices(profiles: ProfileLike[]): FallbackChoice[] {
  const choices: FallbackChoice[] = [];
  for (const profile of profiles) {
    const profileName = profile.display_name || profile.name || profile.id;
    for (const model of profile.models || []) {
      if (!profile.id || !model.id) continue;
      const modelName = model.name || model.model || model.id;
      choices.push({
        profileId: profile.id,
        modelId: model.id,
        label: `${profileName} / ${modelName}`,
      });
    }
  }
  return choices;
}

export function choiceKey(entry: { profile_id: string; model_id: string }): string {
  return `${entry.profile_id}\u0000${entry.model_id}`;
}

/**
 * Drop entries that no longer resolve, collapse duplicates, cap the length.
 *
 * The backend applies the same rules on save; doing it here too keeps a stale
 * row (a deleted profile) from being submitted and bouncing with a 400.
 */
export function sanitizeChain(
  entries: FallbackEntry[],
  choices: FallbackChoice[],
  max = 4,
): FallbackEntry[] {
  const valid = new Set(choices.map((choice) => `${choice.profileId}\u0000${choice.modelId}`));
  const cleaned: FallbackEntry[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    const profileId = String(entry?.profile_id || "").trim();
    const modelId = String(entry?.model_id || "").trim();
    if (!profileId || !modelId) continue;
    const key = `${profileId}\u0000${modelId}`;
    if (!valid.has(key) || seen.has(key)) continue;
    seen.add(key);
    cleaned.push({ profile_id: profileId, model_id: modelId });
    if (cleaned.length >= max) break;
  }
  return cleaned;
}

export function chainsEqual(a: FallbackEntry[], b: FallbackEntry[]): boolean {
  if (a.length !== b.length) return false;
  return a.every(
    (entry, index) =>
      entry.profile_id === b[index].profile_id && entry.model_id === b[index].model_id,
  );
}

/**
 * The chain with the active model removed: retrying the model that just failed
 * as its own fallback would only waste the cooldown.
 */
export function withoutActive(
  entries: FallbackEntry[],
  active: { profile_id?: string | null; model_id?: string | null } | null,
): FallbackEntry[] {
  if (!active?.profile_id || !active.model_id) return entries;
  const key = `${active.profile_id}\u0000${active.model_id}`;
  return entries.filter((entry) => choiceKey(entry) !== key);
}
