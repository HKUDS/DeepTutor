import type { RuntimeStatus } from "@/contracts/generated/turn-protocol";

import { requestJson } from "./client";

export function fetchRuntimeStatus(
  signal?: AbortSignal,
): Promise<RuntimeStatus> {
  return requestJson<RuntimeStatus>("/api/system/runtime", {
    cache: "no-store",
    signal,
    scope: "runtime",
  });
}
