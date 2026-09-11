import type { StorageKey } from "./keys";

export interface StorageEnvelope<T> {
  version: number;
  value: T;
  writtenAt: number;
}

export type ParsedStorageValue<T> =
  | { ok: true; value: T; migrated: boolean }
  | { ok: false; reason: "corrupt" | "invalid" | "version" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function encodeStorageValue<T>(
  key: StorageKey<T>,
  value: T,
  now = Date.now(),
): string {
  return JSON.stringify({ version: key.version, value, writtenAt: now });
}

export function parseStorageValue<T>(
  key: StorageKey<T>,
  raw: string,
): ParsedStorageValue<T> {
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return { ok: false, reason: "corrupt" };
  }
  if (!isRecord(decoded) || typeof decoded.version !== "number") {
    return { ok: false, reason: "invalid" };
  }
  if (decoded.version === key.version) {
    return key.validate(decoded.value)
      ? { ok: true, value: decoded.value, migrated: false }
      : { ok: false, reason: "invalid" };
  }
  const migrated = key.migrate?.(decoded.value, decoded.version) ?? null;
  return migrated !== null && key.validate(migrated)
    ? { ok: true, value: migrated, migrated: true }
    : { ok: false, reason: "version" };
}
