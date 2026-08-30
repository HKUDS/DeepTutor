import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";
import { isConversationReasoningEffort } from "@/lib/reasoning-effort";
import type { LLMSelection } from "@/lib/unified-ws";

const LLM_OPTIONS_CACHE_KEY = "llm-options:list";
const DEFAULT_LLM_OPTIONS_TIMEOUT_MS = 30_000;

export interface LLMOption extends LLMSelection {
  profile_name: string;
  model_name: string;
  model: string;
  provider: string;
  /** Human-readable provider name from the registry ("OpenRouter"). */
  provider_label?: string;
  context_window?: number;
  supported_reasoning_levels?: string[];
  is_active_default: boolean;
}

export interface LLMOptionsResponse {
  active: LLMSelection | null;
  options: LLMOption[];
}

export function llmSelectionKey(selection: LLMSelection | null | undefined) {
  if (!selection?.profile_id || !selection.model_id) return "";
  return `${selection.profile_id}:${selection.model_id}`;
}

export function sameLLMSelection(
  a: LLMSelection | null | undefined,
  b: LLMSelection | null | undefined,
) {
  return llmSelectionKey(a) === llmSelectionKey(b);
}

export function normalizeLLMSelection(value: unknown): LLMSelection | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const profileId =
    typeof record.profile_id === "string" ? record.profile_id.trim() : "";
  const modelId =
    typeof record.model_id === "string" ? record.model_id.trim() : "";
  if (!profileId || !modelId) return null;

  const reasoningEffort =
    typeof record.reasoning_effort === "string"
      ? record.reasoning_effort.trim().toLowerCase()
      : "";
  if (reasoningEffort && !isConversationReasoningEffort(reasoningEffort)) {
    return { profile_id: profileId, model_id: modelId };
  }
  return {
    profile_id: profileId,
    model_id: modelId,
    ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
  };
}

export function withLLMReasoningEffort(
  selection: LLMSelection | null,
  reasoningEffort: string,
): LLMSelection | null {
  if (!selection) return null;
  const normalized = reasoningEffort.trim().toLowerCase();
  if (normalized && !isConversationReasoningEffort(normalized)) return selection;
  return {
    profile_id: selection.profile_id,
    model_id: selection.model_id,
    ...(normalized ? { reasoning_effort: normalized } : {}),
  };
}

/** List the configured model profiles.
 *
 *  Cached so the many consumers that need the model list (composer, model
 *  picker, capability gate, partner forms) share one round-trip instead of
 *  each firing their own on mount. Editing a profile calls
 *  ``invalidateLLMOptionsCache``; pass ``force`` to bypass the cache. */
export async function listLLMOptions(options?: {
  force?: boolean;
  timeoutMs?: number;
}): Promise<LLMOptionsResponse> {
  return withClientCache<LLMOptionsResponse>(
    LLM_OPTIONS_CACHE_KEY,
    async () => {
      const controller = new AbortController();
      const timeout = setTimeout(
        () => controller.abort(),
        options?.timeoutMs ?? DEFAULT_LLM_OPTIONS_TIMEOUT_MS,
      );
      try {
        const response = await apiFetch(
          apiUrl("/api/v1/settings/llm-options"),
          {
            cache: "no-store",
            signal: controller.signal,
          },
        );
        if (!response.ok) {
          throw new Error(`Failed to load LLM options: ${response.status}`);
        }
        const data = (await response.json()) as LLMOptionsResponse;
        return {
          active: data.active ?? null,
          options: Array.isArray(data.options) ? data.options : [],
        };
      } finally {
        clearTimeout(timeout);
      }
    },
    { force: options?.force },
  );
}

export function invalidateLLMOptionsCache(): void {
  invalidateClientCache(LLM_OPTIONS_CACHE_KEY);
}
