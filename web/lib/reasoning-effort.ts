export type ReasoningEffortOption = {
  value: string;
  label: string;
};

/**
 * The wire vocabulary a turn's `llm_selection.reasoning_effort` may carry —
 * mirrors `VALID_REASONING_EFFORTS` in deeptutor/services/model_selection/llm.py.
 * Values outside this set (e.g. provider-specific "adaptive") are rejected by
 * the backend turn contract, so chat-side pickers must filter them out.
 */
export const VALID_REASONING_EFFORTS: ReadonlySet<string> = new Set([
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);

/**
 * Normalize an untrusted reasoning-effort value from persisted state.
 * Returns the lowercase value when it is a legal wire value, else null —
 * illegal values are dropped rather than forwarded to the provider.
 */
export function normalizeReasoningEffort(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return normalized && VALID_REASONING_EFFORTS.has(normalized)
    ? normalized
    : null;
}

const LABELS: Record<string, string> = {
  "": "Provider default (Auto)",
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Maximum",
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
  declaredReasoning?: boolean | null,
): ReasoningEffortOption[] {
  const fromTables = tableReasoningEffortOptions(binding, model, current);
  // A user who declared the model's reasoning support in Settings overrides
  // the tables: "yes" exposes the cross-gateway levels when the tables know
  // nothing, "no" hides the control (a stored value stays visible so it can
  // still be reset).
  if (declaredReasoning === true && fromTables.length === 0) {
    return options(["none", "low", "medium", "high"], current);
  }
  if (declaredReasoning === false) {
    return options([], current);
  }
  return fromTables;
}

function tableReasoningEffortOptions(
  binding: string | null | undefined,
  model: string | null | undefined,
  current: string,
): ReasoningEffortOption[] {
  const canonical = (binding ?? "").trim().toLowerCase().replaceAll("-", "_");
  const provider = PROVIDER_ALIASES[canonical] ?? canonical;
  const modelName = (model ?? "").trim().toLowerCase();

  if (["minimax", "minimax_anthropic"].includes(provider)) {
    if (modelName === "minimax-m3.1-flash") {
      return options(["low", "medium", "high", "xhigh", "max"], current);
    }
    if (modelName === "minimax-m3") {
      return options(["none", "adaptive"], current);
    }
  }

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

  if (
    (OPENAI_PROVIDERS.has(provider) || provider === "custom" || provider === "zhipu") &&
    (modelName === "glm-5.3" || modelName.endsWith("/glm-5.3"))
  ) {
    // GLM-5.3 always thinks; older GLM families have different controls.
    // https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3
    return options(["low", "high", "max"], current);
  }

  if (provider === "custom") {
    // A user-supplied OpenAI-compatible endpoint may route to any upstream
    // model, so expose the common cross-gateway levels and let Auto handle
    // providers without an explicit control.
    return options(["none", "low", "medium", "high"], current);
  }

  if (BINARY_THINKING_PROVIDERS.has(provider)) {
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

  if (OPENAI_PROVIDERS.has(provider)) {
    // gpt-5.6-sol does not share the gpt-5 enum: it takes `none` at the bottom
    // instead of `minimal`, and adds `max` above `xhigh`. It has to be matched
    // before the generic branch, and the two lists stay separate because the
    // other gpt-5.6 variants have not been confirmed to accept `max` — this
    // table exists to keep a rejected level off the menu, so a guess here is
    // the same bug in the other direction.
    //
    // Only the API-key `openai`/`azure_openai` bindings reach this; a managed
    // Codex (OAuth) model is driven by the live
    // `codex_supported_reasoning_levels` from the account catalog instead.
    if (modelName.includes("gpt-5.6-sol")) {
      return options(
        ["none", "low", "medium", "high", "xhigh", "max"],
        current,
      );
    }
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

export function reasoningEffortOptionsFromSupportedLevels(
  values: readonly string[],
): ReasoningEffortOption[] {
  const supported = [
    ...new Set(values.map((value) => value.trim()).filter(Boolean)),
  ];
  return options(supported, "");
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

/**
 * The catalog fields reasoning-effort validation needs from a model option.
 * Structural so `LLMOption` satisfies it without lib → features imports.
 */
export interface ReasoningEffortModelOption {
  provider?: string | null;
  model?: string | null;
  supported_reasoning_efforts?: string[];
  declared_reasoning?: boolean | null;
}

/**
 * The reasoning-effort wire values a selected model supports (#641): the
 * catalog's live `supported_reasoning_efforts` when it publishes one,
 * otherwise the provider/model tables (honouring `declared_reasoning`),
 * narrowed to `VALID_REASONING_EFFORTS`.
 *
 * Unlike the tables' own retention rule, a stored/stale value is NEVER
 * re-added to this list — an unsupported level must not be offered, let
 * alone sent to the provider.
 */
export function supportedReasoningEffortValues(
  option: ReasoningEffortModelOption | null | undefined,
): string[] {
  if (!option) return [];
  const offered =
    option.supported_reasoning_efforts !== undefined
      ? reasoningEffortOptionsFromSupportedLevels(
          option.supported_reasoning_efforts,
        )
      : reasoningEffortOptions(
          option.provider,
          option.model,
          // Deliberately empty: passing the current override would re-add it
          // through the tables' reset-recovery path (#641 review blocker).
          "",
          option.declared_reasoning,
        );
  return offered
    .map((item) => item.value)
    .filter((value) => VALID_REASONING_EFFORTS.has(value));
}

/**
 * The override a turn may actually send for this model: the stored value
 * only when it is in `supportedReasoningEffortValues`, else null (= the
 * configured default / provider default). A null `option` resolves to null
 * — an override that cannot be validated is treated as unsupported.
 */
export function effectiveReasoningEffort(
  option: ReasoningEffortModelOption | null | undefined,
  override: string | null | undefined,
): string | null {
  const normalized = normalizeReasoningEffort(override);
  if (!normalized) return null;
  return supportedReasoningEffortValues(option).includes(normalized)
    ? normalized
    : null;
}

/**
 * Strip `reasoning_effort` from a selection the selected model would reject
 * before the selection is put on the wire (#641).
 *
 * Choice: when `option` is null — options still loading, catalog error, or
 * the profile no longer listed — the override is omitted rather than
 * forwarded. An unvalidatable value is exactly the provider-error case, so
 * the turn safely falls back to the configured default; the persisted
 * conversation selection is left alone for the composer to reconcile once
 * the option resolves.
 */
export function dropUnvalidatedReasoningEffort<
  T extends { reasoning_effort?: string | null },
>(
  selection: T | null,
  option: ReasoningEffortModelOption | null | undefined,
): T | null {
  if (!selection?.reasoning_effort) return selection;
  if (effectiveReasoningEffort(option, selection.reasoning_effort)) {
    return selection;
  }
  const { reasoning_effort: _unvalidated, ...rest } = selection;
  return rest as T;
}
