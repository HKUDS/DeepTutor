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
 * hidden unless a catalog already contains an explicit value, in which case
 * the current value remains visible and can be reset to Auto.
 */
export function reasoningEffortOptions(
  binding: string | null | undefined,
  model: string | null | undefined,
  current = "",
): ReasoningEffortOption[] {
  const provider = (binding ?? "").trim().toLowerCase().replaceAll("-", "_");
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
    const supportsThinking = includesAny(modelName, [
      "claude-3-7",
      "claude-4",
      "claude-sonnet-4",
      "claude-opus-4",
      "claude-haiku-4",
    ]);
    return supportsThinking
      ? options(["none", "low", "medium", "high", "adaptive"], current)
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
