"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiUrl } from "@/lib/api";
import { withClientCache } from "@/lib/client-cache";

/**
 * Which capabilities the backend can actually start a turn with.
 *
 * Not every capability ships in this repository: the Whisper practice room
 * keeps its pages here while `whisper_visitor` / `whisper_trainee` come from an
 * out-of-tree plugin. A surface offering such a feature has to ask before it
 * sends, or the learner gets a raw `Unknown capability: whisper_visitor` from
 * the turn runtime (#963).
 *
 * The registry is fixed for the life of a backend process — installing a
 * plugin needs a restart — so the answer is cached and shared by every caller
 * rather than re-fetched per surface.
 */
export async function listRegisteredCapabilities(): Promise<string[]> {
  return withClientCache(
    "capabilities:registered",
    async () => {
      const res = await apiFetch(apiUrl("/api/v1/capabilities/registered"));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { capabilities?: unknown };
      return Array.isArray(data.capabilities)
        ? data.capabilities.filter((n): n is string => typeof n === "string")
        : [];
    },
    { ttlMs: 300_000 },
  );
}

/** Answers "is this capability installed?" — see {@link useCapabilityFilter}. */
export type CapabilityFilter = (name: string) => boolean;

/**
 * A predicate for gating entry points on whether their capability exists, or
 * `null` while the answer is still in flight.
 *
 * Callers should treat `null` as "not yet" and withhold the gated surface: the
 * probe is a cached local call, so a feature that is installed appears the same
 * way a tile's count does, while one that is missing never flashes into view
 * and out again.
 *
 * The settled predicate fails **open**. An unreachable or older backend answers
 * `true` for everything, so a web bundle newer than its API keeps the pre-#963
 * behaviour instead of hiding features that are really there; only a successful
 * reply that omits a name hides anything.
 */
export function useCapabilityFilter(): CapabilityFilter | null {
  const [filter, setFilter] = useState<CapabilityFilter | null>(null);

  useEffect(() => {
    let cancelled = false;
    listRegisteredCapabilities()
      .then((names) => {
        // Stored through the updater form: a bare `setFilter(fn)` would run
        // `fn` as a state reducer instead of storing it.
        if (!cancelled) setFilter(() => (name: string) => names.includes(name));
      })
      .catch(() => {
        if (!cancelled) setFilter(() => () => true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return filter;
}
