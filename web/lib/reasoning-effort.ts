export type ReasoningEffortOption = {
  value: string;
  label: string;
};

const LABELS: Record<string, string> = {
  "": "Provider default (Auto)",
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  adaptive: "Adaptive",
};

// Mirrors the reasoning-relevant half of PROVIDER_ALIASES in
// deeptutor/services/provider_registry.py. A profile stored as "azure" or
// "openai-compatible" resolves to the same adapter as its canonical name, so
// the lookup below has to see the canonical name or the selector vanishes.
const PROVIDER_ALIASES: Record<string, string> = {
  azure: "azure_openai",
  azureopenai: "azure_openai",
  google: "gemini",
  google_genai: "gemini",
  claude: "anthropic",
  openai_compatible: "custom",
  anthropic_compatible: "custom_anthropic",
};

const OPENAI_PROVIDERS = new Set([
  "openai",
  "azure_openai",
  "openai_codex",
  "github_copilot",
]);
const BINARY_THINKING_PROVIDERS = new Set([
  "deepseek",
  "volcengine",
  "volcengine_coding_plan",
  "byteplus",
  "byteplus_coding_plan",
  "dashscope",
  "minimax",
]);

function includesAny(value: string, patterns: string[]): boolean {
  return patterns.some((pattern) => value.includes(pattern));
}

function options(values: string[], current: string): ReasoningEffortOption[] {
  const normalizedCurrent = current.trim().toLowerCase();
  const resolved = [...values];
  if (normalizedCurrent && !resolved.includes(normalizedCurrent)) {
    resolved.push(normalizedCurrent);
  }
  if (resolved.length === 0) return [];
  return ["", ...resolved].map((value) => ({
    value,
    label: LABELS[value] ?? value,
  }));
}

/**
 * Return conservative reasoning-effort choices for a provider/model pair.
 *
 * The provider adapters do not share one universal enum. In particular,
 * Gemini 3 and Gemini 2.5 Pro reject `none`, while several OpenAI-compatible
 * providers only expose an on/off thinking switch. Unknown model families stay
 * hidden unless a catalog already contains an explicit value.
 *
 * A value already stored for the model is always listed even when this table
 * excludes it, so a hand-edited or newly-invalidated setting stays visible and
 * can be reset to Auto — that is the recovery path for a profile that is
 * currently sending a value its provider rejects.
 */
export function reasoningEffortOptions(
  binding: string | null | undefined,
  model: string | null | undefined,
  current = "",
): ReasoningEffortOption[] {
  const canonical = (binding ?? "").trim().toLowerCase().replaceAll("-", "_");
  const provider = PROVIDER_ALIASES[canonical] ?? canonical;
  const modelName = (model ?? "").trim().toLowerCase();

  if (provider === "gemini" || modelName.includes("gemini")) {
    if (
      modelName.includes("gemini-3") ||
      modelName.includes("gemini-2.5-pro")
    ) {
      return options(["minimal", "low", "medium", "high"], current);
    }
    if (modelName.includes("gemini-2.5")) {
      return options(["none", "low", "medium", "high"], current);
    }
    return options(["low", "medium", "high"], current);
  }

  if (
    provider === "anthropic" ||
    provider === "custom_anthropic" ||
    modelName.includes("claude")
  ) {
    // Effort-based families (Opus 4.7 onward) take `thinking: {type:
    // "adaptive"}` and reject enabled+budget_tokens; the older thinking
    // families are the mirror image and 400 on adaptive. Keep the two lists
    // aligned with _EFFORT_BASED_FAMILIES in
    // deeptutor/services/llm/provider_core/anthropic_provider.py.
    const effortBased = includesAny(modelName, [
      "opus-4-7",
      "opus-4-8",
      "opus-5",
      "sonnet-5",
      "fable-5",
      "mythos-5",
    ]);
    if (effortBased) {
      return options(["none", "adaptive"], current);
    }
    const supportsThinking = includesAny(modelName, [
      "claude-3-7",
      "claude-4",
      "claude-sonnet-4",
      "claude-opus-4",
      "claude-haiku-4",
    ]);
    return supportsThinking
      ? options(["none", "low", "medium", "high"], current)
      : options([], current);
  }

  if (BINARY_THINKING_PROVIDERS.has(provider) || provider === "custom") {
    const supported =
      provider === "minimax" ||
      includesAny(modelName, [
        "deepseek-reasoner",
        "deepseek-v4-pro",
        "qwen3",
        "qwen-3",
        "qwq",
        "qwen-plus",
      ]);
    if (supported) {
      return options(["minimal", "high"], current);
    }
    if (BINARY_THINKING_PROVIDERS.has(provider)) {
      // Deliberately no selector for the rest — VolcEngine/BytePlus thinking
      // models are switched on by the backend from the spec's
      // reasoning_model_patterns, so an explicit per-model choice here would
      // duplicate a decision the registry already owns.
      return options([], current);
    }
  }

  if (OPENAI_PROVIDERS.has(provider) || provider === "custom") {
    const isGpt5OrCodex = includesAny(modelName, ["gpt-5", "codex"]);
    if (isGpt5OrCodex) {
      return options(["minimal", "low", "medium", "high", "xhigh"], current);
    }
    if (includesAny(modelName, ["o1", "o3", "o4"])) {
      return options(["low", "medium", "high"], current);
    }
    return options([], current);
  }

  return options([], current);
}

export function setModelReasoningEffort(
  model: { reasoning_effort?: string },
  value: string,
): void {
  const normalized = value.trim();
  if (normalized) {
    model.reasoning_effort = normalized;
  } else {
    delete model.reasoning_effort;
  }
}
