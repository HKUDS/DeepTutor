import { clampPanelRatio } from "../model/editor-state";

export const DRAFT_STORAGE_VERSION = 2 as const;
export const DRAFT_STORAGE_PREFIX = "deeptutor.co_writer.draft.v2.";
export const LEGACY_DRAFT_STORAGE_PREFIX = "deeptutor.co_writer.draft.";
export const SPLIT_RATIO_KEY = "deeptutor.co_writer.split_ratio.v2";
export const SYNC_SCROLL_KEY = "deeptutor.co_writer.sync_scroll.v2";

export interface StoredDraft {
  version: typeof DRAFT_STORAGE_VERSION;
  docId: string;
  content: string;
  revision: number;
  updatedAt: number;
}

export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function draftKey(docId: string): string {
  return `${DRAFT_STORAGE_PREFIX}${encodeURIComponent(docId)}`;
}

function legacyDraftKey(docId: string): string {
  return `${LEGACY_DRAFT_STORAGE_PREFIX}${docId}`;
}

function parseStoredDraft(
  value: string | null,
  docId: string,
): StoredDraft | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Partial<StoredDraft>;
    if (
      parsed.version !== DRAFT_STORAGE_VERSION ||
      parsed.docId !== docId ||
      typeof parsed.content !== "string" ||
      !Number.isInteger(parsed.revision) ||
      typeof parsed.updatedAt !== "number"
    ) {
      return null;
    }
    return parsed as StoredDraft;
  } catch {
    return null;
  }
}

export function loadDraft(
  storage: KeyValueStorage,
  docId: string,
): StoredDraft | null {
  try {
    const current = parseStoredDraft(storage.getItem(draftKey(docId)), docId);
    if (current) return current;

    const legacyKey = legacyDraftKey(docId);
    const legacyContent = storage.getItem(legacyKey);
    if (legacyContent === null) return null;
    const migrated = saveDraft(storage, docId, legacyContent, 0);
    storage.removeItem(legacyKey);
    return migrated;
  } catch {
    return null;
  }
}

export function saveDraft(
  storage: KeyValueStorage,
  docId: string,
  content: string,
  revision: number,
  now = Date.now(),
): StoredDraft | null {
  const draft: StoredDraft = {
    version: DRAFT_STORAGE_VERSION,
    docId,
    content,
    revision: Math.max(0, Math.trunc(revision)),
    updatedAt: now,
  };
  try {
    storage.setItem(draftKey(docId), JSON.stringify(draft));
    return draft;
  } catch {
    return null;
  }
}

export function clearDraft(storage: KeyValueStorage, docId: string): boolean {
  try {
    storage.removeItem(draftKey(docId));
    storage.removeItem(legacyDraftKey(docId));
    return true;
  } catch {
    return false;
  }
}

export function loadSplitRatio(storage: KeyValueStorage): number {
  try {
    return clampPanelRatio(
      Number.parseFloat(storage.getItem(SPLIT_RATIO_KEY) ?? ""),
    );
  } catch {
    return 0.5;
  }
}

export function saveSplitRatio(
  storage: KeyValueStorage,
  ratio: number,
): boolean {
  try {
    storage.setItem(SPLIT_RATIO_KEY, String(clampPanelRatio(ratio)));
    return true;
  } catch {
    return false;
  }
}

export function loadSynchronizedScroll(storage: KeyValueStorage): boolean {
  try {
    return storage.getItem(SYNC_SCROLL_KEY) !== "0";
  } catch {
    return true;
  }
}

export function saveSynchronizedScroll(
  storage: KeyValueStorage,
  enabled: boolean,
): boolean {
  try {
    storage.setItem(SYNC_SCROLL_KEY, enabled ? "1" : "0");
    return true;
  } catch {
    return false;
  }
}
