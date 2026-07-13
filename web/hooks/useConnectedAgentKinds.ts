"use client";

import { useEffect, useState } from "react";
import { listSubagentConnections } from "@/lib/subagents-api";

/**
 * Shared, lazily-fetched `connection name → backend kind` map for connected
 * subagents. Used to badge a selected agent (a `type: subagent` KB) with its
 * real brand icon instead of the generic knowledge-base icon wherever only the
 * KB name is known (e.g. the sent-message reference chip).
 *
 * Module-cached so it fetches once across all consumers; returns `{}` until
 * loaded, so callers degrade gracefully to the default icon.
 */
let cache: Record<string, string> | null = null;
let inflight: Promise<void> | null = null;
const listeners = new Set<(map: Record<string, string>) => void>();

function ensureLoaded(): void {
  if (cache || inflight) return;
  inflight = listSubagentConnections()
    .then((conns) => {
      cache = Object.fromEntries(conns.map((c) => [c.name, c.agent_kind]));
      for (const l of listeners) l(cache);
    })
    .catch(() => {
      cache = {};
    })
    .finally(() => {
      inflight = null;
    });
}

export function useConnectedAgentKinds(): Record<string, string> {
  const [map, setMap] = useState<Record<string, string>>(() => cache ?? {});
  useEffect(() => {
    listeners.add(setMap);
    if (cache) {
      // Loaded by another consumer between our render and this effect — deliver
      // it off the effect body (avoids a synchronous setState-in-effect).
      const loaded = cache;
      queueMicrotask(() => setMap(loaded));
    } else {
      ensureLoaded();
    }
    return () => {
      listeners.delete(setMap);
    };
  }, []);
  return map;
}
