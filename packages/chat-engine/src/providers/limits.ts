import { createHash } from "node:crypto";
import type { ProviderConfig } from "../native/types.js";

interface Bucket {
  active: number;
  starts: number[];
  waiters: Set<() => void>;
  touched: number;
}
const buckets = new Map<string, Bucket>();

function wait(
  bucket: Bucket,
  signal: AbortSignal,
  delay: number,
): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const finish = () => {
      clearTimeout(timer);
      bucket.waiters.delete(finish);
      signal.removeEventListener("abort", abort);
      resolve();
    };
    const abort = () => {
      clearTimeout(timer);
      bucket.waiters.delete(finish);
      signal.removeEventListener("abort", abort);
      reject(signal.reason);
    };
    const timer = setTimeout(finish, delay);
    bucket.waiters.add(finish);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Shared by turns using one provider identity; neither keys nor prompts are retained. */
export async function withProviderLimit<T>(
  config: ProviderConfig,
  signal: AbortSignal,
  operation: () => Promise<T>,
): Promise<T> {
  const key = createHash("sha256")
    .update(
      JSON.stringify([
        config.endpoint,
        config.model,
        config.apiKey,
        config.headers,
      ]),
    )
    .digest("hex");
  let bucket = buckets.get(key);
  if (!bucket) {
    if (buckets.size >= 128) {
      for (const [id, item] of buckets)
        if (
          !item.active &&
          !item.waiters.size &&
          Date.now() - item.touched >= 60_000
        )
          buckets.delete(id);
      if (buckets.size >= 128)
        throw new Error("Native model admission is at capacity");
    }
    bucket = { active: 0, starts: [], waiters: new Set(), touched: Date.now() };
    buckets.set(key, bucket);
  }
  const concurrent = Math.max(1, Math.min(128, config.maxConcurrency || 20));
  const rate = Math.max(1, Math.min(100_000, config.requestsPerMinute || 600));
  while (true) {
    signal.throwIfAborted();
    const now = Date.now();
    bucket.starts = bucket.starts.filter((start) => now - start < 60_000);
    if (bucket.active < concurrent && bucket.starts.length < rate) break;
    await wait(
      bucket,
      signal,
      bucket.starts.length >= rate
        ? Math.max(1, bucket.starts[0]! + 60_000 - now)
        : 60_000,
    );
  }
  bucket.active++;
  bucket.starts.push(Date.now());
  bucket.touched = Date.now();
  try {
    return await operation();
  } finally {
    bucket.active--;
    bucket.touched = Date.now();
    for (const wake of [...bucket.waiters]) wake();
  }
}
