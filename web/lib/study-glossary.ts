/**
 * The terms a learner stopped on, per study session.
 *
 * The tutor uses vocabulary before it defines it; when a learner asks "what
 * does this word mean", the answer is worth keeping. This is deliberately
 * small and local: a term is a string, the list is capped, and it is keyed by
 * session so moving to the next knowledge point starts clean. Reading it back
 * is what lets the study screen show a running glossary instead of making the
 * learner scroll up to find the one word they looked up.
 */

import { browserStorage } from "@/shared/storage";

const KEY_PREFIX = "dt.mastery.glossary:";
const MAX_TERMS = 40;
const MAX_TERM_LENGTH = 80;

/** Normalize for comparison: trim, collapse spaces, cap the length. */
export function normalizeGlossaryTerm(term: string): string {
  return term.replace(/\s+/g, " ").trim().slice(0, MAX_TERM_LENGTH);
}

export function loadGlossary(sessionId: string | null | undefined): string[] {
  if (!sessionId || typeof window === "undefined") return [];
  try {
    const raw = browserStorage.readRaw("local", KEY_PREFIX + sessionId);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((term): term is string => typeof term === "string")
      .map(normalizeGlossaryTerm)
      .filter(Boolean);
  } catch {
    return [];
  }
}

function saveGlossary(sessionId: string, terms: string[]): void {
  try {
    browserStorage.writeRaw(
      "local",
      KEY_PREFIX + sessionId,
      JSON.stringify(terms.slice(0, MAX_TERMS)),
    );
  } catch {
    // Storage is unavailable; the session still works, it just forgets.
  }
}

/** Add a term, keeping the list unique and capped. Returns the next list. */
export function addGlossaryTerm(
  sessionId: string | null | undefined,
  current: string[],
  term: string,
): string[] {
  const normalized = normalizeGlossaryTerm(term);
  if (!sessionId || !normalized) return current;
  if (current.some((entry) => entry.toLowerCase() === normalized.toLowerCase())) {
    return current;
  }
  const next = [normalized, ...current].slice(0, MAX_TERMS);
  saveGlossary(sessionId, next);
  return next;
}

export function removeGlossaryTerm(
  sessionId: string | null | undefined,
  current: string[],
  term: string,
): string[] {
  if (!sessionId) return current;
  const next = current.filter((entry) => entry !== term);
  saveGlossary(sessionId, next);
  return next;
}
