import { apiFetch, apiUrl } from "@/lib/api";
import { withClientCache } from "@/lib/client-cache";

import {
  parseCapabilityCatalogPayload,
  type CapabilityDescriptor,
} from "./model";

export async function fetchCapabilityCatalog(options?: {
  force?: boolean;
}): Promise<CapabilityDescriptor[]> {
  return withClientCache(
    "capabilities:catalog",
    async () => {
      const response = await apiFetch(apiUrl("/api/capabilities/registered"));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return parseCapabilityCatalogPayload(await response.json());
    },
    { force: options?.force, ttlMs: 300_000 },
  );
}
