import type { DictionaryResult } from "@/lib/immersive-reading-api";

/**
 * Module-level in-memory cache for dictionary lookups.
 *
 * Keyed by word only — the definitions don't change across contexts.  The
 * `context_match` flags may differ per sentence, but that's a cosmetic
 * highlight; showing the cached definitions instantly is the priority
 * ("trade space for time").  The backend recomputes context_match on every
 * request, so a refresh (or the first lookup for a new context) still gets
 * the correct highlighting.
 */

const MAX_ENTRIES = 200;
const _cache = new Map<string, DictionaryResult>();

/** Move a key to the most-recently-used position (Map preserves insertion order). */
function touch(key: string, value: DictionaryResult): void {
  _cache.delete(key);
  _cache.set(key, value);
  while (_cache.size > MAX_ENTRIES) {
    const oldest = _cache.keys().next().value;
    if (oldest === undefined) break;
    _cache.delete(oldest);
  }
}

/** Returns a cached result for *word*, or null. Does not mutate. */
export function getCachedWord(word: string): DictionaryResult | null {
  const key = word.toLowerCase();
  const entry = _cache.get(key);
  if (entry) touch(key, entry); // refresh LRU position
  return entry ?? null;
}

/** Stores a lookup result in the cache. */
export function setCachedWord(word: string, result: DictionaryResult): void {
  touch(word.toLowerCase(), result);
}

/** Clears the entire cache (e.g. when switching documents). */
export function clearDictionaryCache(): void {
  _cache.clear();
}

// ── Translation cache ────────────────────────────────────────────────────
//
// Keyed by `${text}::${targetLang}`. The LRU strategy mirrors the dictionary
// cache above.

const _translationCache = new Map<string, string>();

function _translationKey(text: string, targetLang: string): string {
  return `${text}::${targetLang}`;
}

/** Returns a cached translation, or null. Does not mutate. */
export function getCachedTranslation(
  text: string,
  targetLang: string,
): string | null {
  const key = _translationKey(text, targetLang);
  const entry = _translationCache.get(key);
  if (entry !== undefined) {
    // refresh LRU position
    _translationCache.delete(key);
    _translationCache.set(key, entry);
  }
  return entry ?? null;
}

/** Stores a translation result in the cache. */
export function setCachedTranslation(
  text: string,
  targetLang: string,
  translation: string,
): void {
  const key = _translationKey(text, targetLang);
  _translationCache.delete(key);
  _translationCache.set(key, translation);
  while (_translationCache.size > MAX_ENTRIES) {
    const oldest = _translationCache.keys().next().value;
    if (oldest === undefined) break;
    _translationCache.delete(oldest);
  }
}

/** Clears the translation cache (e.g. when switching documents). */
export function clearTranslationCache(): void {
  _translationCache.clear();
}
