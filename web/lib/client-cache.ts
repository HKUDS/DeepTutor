import { activeWorkspaceId } from "./workspace-scope";

type CacheEntry<T> = {
  data?: T;
  promise?: Promise<T>;
  expiresAt: number;
};

const clientCache = new Map<string, CacheEntry<unknown>>();

interface CacheOptions {
  ttlMs?: number;
  force?: boolean;
}

export async function withClientCache<T>(
  key: string,
  loader: () => Promise<T>,
  options: CacheOptions = {},
): Promise<T> {
  const { ttlMs = 30_000, force = false } = options;

  if (typeof window === "undefined") {
    return loader();
  }

  const now = Date.now();
  key = `${key}:workspace=${activeWorkspaceId()}`;
  const cached = clientCache.get(key) as CacheEntry<T> | undefined;
  if (!force && cached) {
    if (cached.data !== undefined && cached.expiresAt > now) {
      return cached.data;
    }
    if (cached.promise) {
      return cached.promise;
    }
  }

  const promise = loader()
    .then((value) => {
      // Invalidated or superseded requests must not repopulate stale data.
      if (clientCache.get(key)?.promise === promise) {
        clientCache.set(key, {
          data: value,
          expiresAt: Date.now() + ttlMs,
        });
      }
      return value;
    })
    .catch((error) => {
      if (clientCache.get(key)?.promise === promise) clientCache.delete(key);
      throw error;
    });

  clientCache.set(key, {
    promise,
    expiresAt: now + ttlMs,
  });

  return promise;
}

export function invalidateClientCache(prefix: string): void {
  for (const key of clientCache.keys()) {
    if (key.startsWith(prefix)) {
      clientCache.delete(key);
    }
  }
}
