/* ────────────────────────────────────────────────────────────────────────
 * Feynman learning → chat handoff contract (UI-01).
 *
 * The Feynman workspace never fabricates evidence client-side. Text send,
 * confirmed voice transcript and help requests are all persisted server-side
 * only through the existing Mastery Path chat: the workspace stashes the
 * *draft* the learner is about to send into a scoped, versioned sessionStorage
 * slot, then navigates to the same session at /home/{pathId}. The chat page
 * consumes the slot exactly once, selects the mastery_path capability and
 * prefills the real composer; the learner confirms before anything reaches the
 * tutor.
 *
 * The contract deliberately carries no secrets, no evidence ids and no server
 * state — only the draft text plus a source kind. A malformed, expired,
 * wrong-session or unsupported-version handoff is discarded safely.
 * ──────────────────────────────────────────────────────────────────────── */

export const FEYNMAN_HANDOFF_VERSION = 1;
export const FEYNMAN_HANDOFF_TTL_MS = 5 * 60 * 1000;
export const FEYNMAN_HANDOFF_STORAGE_PREFIX = "dt:feynman:handoff";

export type FeynmanHandoffKind = "text" | "voice_transcript" | "help";

export interface FeynmanHandoff {
  version: number;
  pathId: string;
  kind: FeynmanHandoffKind;
  draft: string;
  createdAt: number;
}

/** Minimal Storage shim so the pure contract is unit-testable in Node. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const HANDOFF_KINDS: ReadonlySet<string> = new Set<FeynmanHandoffKind>([
  "text",
  "voice_transcript",
  "help",
]);

export function feynmanHandoffKey(pathId: string): string {
  return `${FEYNMAN_HANDOFF_STORAGE_PREFIX}:${pathId}`;
}

/**
 * Parse + validate a raw handoff for a path. Returns the handoff when valid;
 * otherwise null (malformed JSON, wrong shape, wrong session, expired, or
 * unsupported version). Callers must remove the slot either way so a stale
 * entry can never be replayed.
 */
export function parseFeynmanHandoff(
  raw: string | null,
  pathId: string,
  now: number = Date.now(),
): FeynmanHandoff | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const p = parsed as Partial<FeynmanHandoff>;
  if (typeof p.version !== "number" || p.version !== FEYNMAN_HANDOFF_VERSION) {
    return null;
  }
  if (typeof p.pathId !== "string" || p.pathId !== pathId) return null;
  if (typeof p.kind !== "string" || !HANDOFF_KINDS.has(p.kind)) return null;
  if (typeof p.draft !== "string" || !p.draft.trim()) return null;
  if (typeof p.createdAt !== "number" || !Number.isFinite(p.createdAt)) {
    return null;
  }
  const age = now - p.createdAt;
  if (age < 0 || age > FEYNMAN_HANDOFF_TTL_MS) return null;
  return {
    version: FEYNMAN_HANDOFF_VERSION,
    pathId: p.pathId,
    kind: p.kind as FeynmanHandoffKind,
    draft: p.draft,
    createdAt: p.createdAt,
  };
}

/** Write a handoff for a path. Empty drafts are ignored. */
export function writeFeynmanHandoff(
  storage: StorageLike,
  pathId: string,
  kind: FeynmanHandoffKind,
  draft: string,
  now: number = Date.now(),
): void {
  const text = draft.trim();
  if (!text) return;
  const handoff: FeynmanHandoff = {
    version: FEYNMAN_HANDOFF_VERSION,
    pathId,
    kind,
    draft: text,
    createdAt: now,
  };
  storage.setItem(feynmanHandoffKey(pathId), JSON.stringify(handoff));
}

/**
 * Consume a handoff for a path exactly once. Always removes the slot (so a
 * stale entry can never be replayed); returns the handoff only when valid.
 */
export function consumeFeynmanHandoff(
  storage: StorageLike,
  pathId: string,
  now: number = Date.now(),
): FeynmanHandoff | null {
  const key = feynmanHandoffKey(pathId);
  const handoff = parseFeynmanHandoff(storage.getItem(key), pathId, now);
  storage.removeItem(key);
  return handoff;
}

/* ── Browser wrappers (SSR-safe) ──────────────────────────────────────── */

export function writeBrowserFeynmanHandoff(
  pathId: string,
  kind: FeynmanHandoffKind,
  draft: string,
): void {
  if (typeof window === "undefined") return;
  writeFeynmanHandoff(window.sessionStorage, pathId, kind, draft);
}

export function consumeBrowserFeynmanHandoff(pathId: string): FeynmanHandoff | null {
  if (typeof window === "undefined") return null;
  return consumeFeynmanHandoff(window.sessionStorage, pathId);
}
