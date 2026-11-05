import type { LLMSelection } from "@/features/chat/model/protocol";
import { browserStorage } from "@/shared/storage";

const KEY_PREFIX = "deeptutor.pendingLLMSelection.";
const pending = new Map<string, LLMSelection | null>();

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function cloneSelection(raw: unknown): LLMSelection | null {
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  const profileId = record.profile_id;
  const modelId = record.model_id;
  if (!isNonEmptyString(profileId) || !isNonEmptyString(modelId)) return null;
  return { profile_id: profileId, model_id: modelId };
}

export function setPendingLLMSelection(
  scope: string,
  selection: LLMSelection | null,
): void {
  const trimmed = scope.trim();
  if (typeof window === "undefined" || trimmed.length === 0) return;
  const key = KEY_PREFIX + trimmed;
  const clone =
    selection === null
      ? null
      : { profile_id: selection.profile_id, model_id: selection.model_id };
  pending.set(trimmed, clone);
  try {
    if (clone === null) {
      browserStorage.removeRaw("session", key);
    } else {
      browserStorage.writeRaw("session", key, JSON.stringify(clone));
    }
  } catch {
    // The in-memory value remains authoritative when browser storage fails.
  }
}

export function consumePendingLLMSelection(scope: string): LLMSelection | null {
  const trimmed = scope.trim();
  if (typeof window === "undefined" || trimmed.length === 0) return null;
  const key = KEY_PREFIX + trimmed;
  let stored: LLMSelection | null;
  if (pending.has(trimmed)) {
    stored = pending.get(trimmed) ?? null;
  } else {
    try {
      const raw = browserStorage.readRaw("session", key);
      stored = raw === null ? null : cloneSelection(JSON.parse(raw));
    } catch {
      stored = null;
    }
  }
  pending.set(trimmed, null);
  try {
    browserStorage.removeRaw("session", key);
  } catch {
    // The in-memory value remains authoritative when browser storage fails.
  }
  return stored === null
    ? null
    : { profile_id: stored.profile_id, model_id: stored.model_id };
}
