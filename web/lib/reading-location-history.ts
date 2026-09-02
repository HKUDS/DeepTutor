import type { UnitKind } from "@/lib/reading-api";
import { browserStorage } from "@/shared/storage";

export const READING_HISTORY_LIMIT = 50;
const STORAGE_PREFIX = "dt.reader.history.";

export interface ReadingLocationSource {
  filename?: string;
  unit?: UnitKind;
  mime?: string;
  renderMode?: string;
}

export interface ReadingLocationEntry {
  materialId: string;
  locator: number;
  title: string;
  source?: ReadingLocationSource;
}

export interface ReadingLocationHistory {
  entries: ReadingLocationEntry[];
  index: number;
}

export const EMPTY_READING_HISTORY: ReadingLocationHistory = {
  entries: [],
  index: -1,
};

function normalizeEntry(value: unknown): ReadingLocationEntry | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const materialId = String(row.materialId ?? "")
    .trim()
    .toLowerCase();
  const locator = Number(row.locator);
  if (!/^[0-9a-f]{8,64}$/.test(materialId)) return null;
  if (!Number.isInteger(locator) || locator < 1) return null;
  const rawSource =
    row.source && typeof row.source === "object"
      ? (row.source as Record<string, unknown>)
      : null;
  const unit =
    rawSource &&
    typeof rawSource.unit === "string" &&
    ["page", "chapter", "slide", "section"].includes(rawSource.unit)
      ? (rawSource.unit as UnitKind)
      : undefined;
  const source = rawSource
    ? {
        ...(typeof rawSource.filename === "string"
          ? { filename: rawSource.filename }
          : {}),
        ...(unit ? { unit } : {}),
        ...(typeof rawSource.mime === "string" ? { mime: rawSource.mime } : {}),
        ...(typeof rawSource.renderMode === "string"
          ? { renderMode: rawSource.renderMode }
          : {}),
      }
    : undefined;
  return {
    materialId,
    locator,
    title:
      typeof row.title === "string" && row.title.trim()
        ? row.title.trim()
        : source?.filename || materialId,
    ...(source && Object.keys(source).length ? { source } : {}),
  };
}

function sameLocation(
  a: ReadingLocationEntry,
  b: ReadingLocationEntry,
): boolean {
  return a.materialId === b.materialId && a.locator === b.locator;
}

export function pushReadingLocation(
  history: ReadingLocationHistory,
  entry: ReadingLocationEntry,
): ReadingLocationHistory {
  const normalized = normalizeEntry(entry);
  if (!normalized) return history;
  const current = history.entries[history.index];
  if (current && sameLocation(current, normalized)) {
    const entries = [...history.entries];
    entries[history.index] = normalized;
    return { entries, index: history.index };
  }
  const entries = [...history.entries.slice(0, history.index + 1), normalized];
  const trimmed = entries.slice(-READING_HISTORY_LIMIT);
  return { entries: trimmed, index: trimmed.length - 1 };
}

/** Manual scroll updates the current location without creating history noise. */
export function replaceCurrentReadingLocation(
  history: ReadingLocationHistory,
  entry: ReadingLocationEntry,
): ReadingLocationHistory {
  const normalized = normalizeEntry(entry);
  if (!normalized) return history;
  if (history.index < 0 || !history.entries[history.index]) {
    return pushReadingLocation(history, normalized);
  }
  const entries = [...history.entries];
  entries[history.index] = normalized;
  return { entries, index: history.index };
}

export function moveReadingHistory(
  history: ReadingLocationHistory,
  delta: -1 | 1,
): ReadingLocationHistory {
  const index = Math.max(
    0,
    Math.min(history.entries.length - 1, history.index + delta),
  );
  return history.entries.length ? { ...history, index } : history;
}

export function selectReadingHistoryIndex(
  history: ReadingLocationHistory,
  index: number,
): ReadingLocationHistory {
  if (
    !Number.isInteger(index) ||
    index < 0 ||
    index >= history.entries.length
  ) {
    return history;
  }
  return { ...history, index };
}

export function parseReadingHistory(
  value: string | null,
): ReadingLocationHistory {
  if (!value) return EMPTY_READING_HISTORY;
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const rawEntries = Array.isArray(parsed.entries) ? parsed.entries : [];
    const normalized: Array<{
      entry: ReadingLocationEntry;
      firstRawIndex: number;
    }> = [];
    rawEntries.forEach((value, rawIndex) => {
      const entry = normalizeEntry(value);
      if (!entry) return;
      const previous = normalized[normalized.length - 1];
      if (previous && sameLocation(previous.entry, entry)) {
        previous.entry = entry;
        return;
      }
      normalized.push({ entry, firstRawIndex: rawIndex });
    });
    if (!normalized.length) return EMPTY_READING_HISTORY;

    const rawIndex = Number(parsed.index);
    const selected = Number.isInteger(rawIndex)
      ? normalized.findLastIndex((row) => row.firstRawIndex <= rawIndex)
      : normalized.length - 1;
    const trimStart = Math.max(0, normalized.length - READING_HISTORY_LIMIT);
    const entries = normalized.slice(trimStart).map(({ entry }) => entry);
    const index = Math.max(
      0,
      Math.min(entries.length - 1, Math.max(0, selected) - trimStart),
    );
    return { entries, index };
  } catch {
    return EMPTY_READING_HISTORY;
  }
}

export function readingHistoryStorageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(sessionId)}`;
}

export function loadReadingHistory(sessionId: string): ReadingLocationHistory {
  if (!sessionId || typeof window === "undefined") return EMPTY_READING_HISTORY;
  try {
    return parseReadingHistory(
      browserStorage.readRaw("local", readingHistoryStorageKey(sessionId)),
    );
  } catch {
    return EMPTY_READING_HISTORY;
  }
}

export function saveReadingHistory(
  sessionId: string,
  history: ReadingLocationHistory,
): void {
  if (!sessionId || typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      readingHistoryStorageKey(sessionId),
      JSON.stringify(history),
    );
  } catch {
    // Storage may be unavailable or full; navigation still works in memory.
  }
}
