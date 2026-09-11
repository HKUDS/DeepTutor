import {
  STORAGE_NAMESPACE,
  physicalStorageKey,
  type StorageKey,
  type StorageScope,
} from "./keys";
import { encodeStorageValue, parseStorageValue } from "./schema";

export interface StorageLike {
  readonly length: number;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  key(index: number): string | null;
}

export interface StorageEventLike {
  key: string | null;
  newValue: string | null;
  storageArea?: StorageLike | null;
}

export interface StorageEventTargetLike {
  addEventListener(
    type: "storage",
    listener: (event: StorageEventLike) => void,
  ): void;
  removeEventListener(
    type: "storage",
    listener: (event: StorageEventLike) => void,
  ): void;
}

export class StorageStore {
  constructor(
    private readonly providers: Partial<Record<StorageScope, StorageLike>>,
    private readonly events?: StorageEventTargetLike,
  ) {}

  private provider(scope: StorageScope): StorageLike | undefined {
    return this.providers[scope];
  }

  read<T>(key: StorageKey<T>): T {
    const storage = this.provider(key.scope);
    if (!storage) return key.fallback;
    try {
      const raw = storage.getItem(physicalStorageKey(key));
      if (raw === null) return key.fallback;
      const parsed = parseStorageValue(key, raw);
      if (!parsed.ok) return key.fallback;
      if (parsed.migrated) this.write(key, parsed.value);
      return parsed.value;
    } catch {
      return key.fallback;
    }
  }

  write<T>(key: StorageKey<T>, value: T): boolean {
    const storage = this.provider(key.scope);
    if (!storage || !key.validate(value)) return false;
    try {
      storage.setItem(physicalStorageKey(key), encodeStorageValue(key, value));
      return true;
    } catch {
      return false;
    }
  }

  remove<T>(key: StorageKey<T>): boolean {
    const storage = this.provider(key.scope);
    if (!storage) return false;
    try {
      storage.removeItem(physicalStorageKey(key));
      return true;
    } catch {
      return false;
    }
  }

  readRaw(scope: StorageScope, name: string): string | null {
    try {
      return this.provider(scope)?.getItem(name) ?? null;
    } catch {
      return null;
    }
  }

  writeRaw(scope: StorageScope, name: string, value: string): boolean {
    try {
      const storage = this.provider(scope);
      if (!storage) return false;
      storage.setItem(name, value);
      return true;
    } catch {
      return false;
    }
  }

  removeRaw(scope: StorageScope, name: string): boolean {
    try {
      const storage = this.provider(scope);
      if (!storage) return false;
      storage.removeItem(name);
      return true;
    } catch {
      return false;
    }
  }

  clearNamespace(scope: StorageScope, namePrefix = ""): number {
    const storage = this.provider(scope);
    if (!storage) return 0;
    const prefix = `${STORAGE_NAMESPACE}${scope}:${namePrefix}`;
    const matches: string[] = [];
    try {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key?.startsWith(prefix)) matches.push(key);
      }
      for (const key of matches) storage.removeItem(key);
      return matches.length;
    } catch {
      return 0;
    }
  }

  subscribe<T>(key: StorageKey<T>, listener: (value: T) => void): () => void {
    const events = this.events;
    if (!events) return () => undefined;
    const expected = physicalStorageKey(key);
    const storage = this.provider(key.scope);
    const onStorage = (event: StorageEventLike) => {
      if (event.key !== expected) return;
      if (event.storageArea && storage && event.storageArea !== storage) return;
      if (event.newValue === null) {
        listener(key.fallback);
        return;
      }
      const parsed = parseStorageValue(key, event.newValue);
      if (parsed.ok) listener(parsed.value);
    };
    events.addEventListener("storage", onStorage);
    return () => events.removeEventListener("storage", onStorage);
  }
}

export function createBrowserStorageStore(): StorageStore {
  if (typeof window === "undefined") return new StorageStore({});
  return new StorageStore(
    { local: window.localStorage, session: window.sessionStorage },
    window as unknown as StorageEventTargetLike,
  );
}

class BrowserStorageStore extends StorageStore {
  constructor() {
    super({});
  }

  override read<T>(key: StorageKey<T>): T {
    return createBrowserStorageStore().read(key);
  }

  override write<T>(key: StorageKey<T>, value: T): boolean {
    return createBrowserStorageStore().write(key, value);
  }

  override remove<T>(key: StorageKey<T>): boolean {
    return createBrowserStorageStore().remove(key);
  }

  override readRaw(scope: StorageScope, name: string): string | null {
    return createBrowserStorageStore().readRaw(scope, name);
  }

  override writeRaw(scope: StorageScope, name: string, value: string): boolean {
    return createBrowserStorageStore().writeRaw(scope, name, value);
  }

  override removeRaw(scope: StorageScope, name: string): boolean {
    return createBrowserStorageStore().removeRaw(scope, name);
  }

  override clearNamespace(scope: StorageScope, namePrefix = ""): number {
    return createBrowserStorageStore().clearNamespace(scope, namePrefix);
  }

  override subscribe<T>(key: StorageKey<T>, listener: (value: T) => void) {
    return createBrowserStorageStore().subscribe(key, listener);
  }
}

export const browserStorage = new BrowserStorageStore();
