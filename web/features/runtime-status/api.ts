import { requestJson } from "@/shared/api/client";
import { parseRuntimeStatus, type RuntimeStatusModel } from "./model";

export const RUNTIME_STATUS_PATH = "/api/system/runtime";

export async function fetchRuntimeStatus(
  signal?: AbortSignal,
): Promise<RuntimeStatusModel> {
  const payload = await requestJson<unknown>(RUNTIME_STATUS_PATH, {
    cache: "no-store",
    signal,
    scope: "runtime",
  });
  return parseRuntimeStatus(payload);
}
