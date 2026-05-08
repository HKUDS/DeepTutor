import { apiFetch, apiUrl } from "@/lib/api";
import type { LLMSelection } from "@/lib/unified-ws";

export interface LLMOption extends LLMSelection {
  profile_name: string;
  model_name: string;
  model: string;
  provider: string;
  context_window?: number;
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

export async function listLLMOptions(): Promise<LLMOptionsResponse> {
  const response = await apiFetch(apiUrl("/api/v1/settings/llm-options"), {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to load LLM options: ${response.status}`);
  }
  const data = (await response.json()) as LLMOptionsResponse;
  return {
    active: data.active ?? null,
    options: Array.isArray(data.options) ? data.options : [],
  };
}
