export const STORAGE_NAMESPACE = "deeptutor:v2:";

export type StorageScope = "local" | "session";

export interface StorageKey<T> {
  name: string;
  scope: StorageScope;
  version: number;
  fallback: T;
  validate: (value: unknown) => value is T;
  migrate?: (value: unknown, fromVersion: number) => T | null;
}

export function defineStorageKey<T>(key: StorageKey<T>): StorageKey<T> {
  return Object.freeze({ ...key });
}

export function physicalStorageKey<T>(key: StorageKey<T>): string {
  return `${STORAGE_NAMESPACE}${key.scope}:${key.name}`;
}

export function dynamicStorageKey<T>(
  base: Omit<StorageKey<T>, "name">,
  name: string,
): StorageKey<T> {
  return defineStorageKey({ ...base, name });
}
