"use client";

import { useMemo, useRef, useState } from "react";
import { Brain, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useOutsideClick } from "@/hooks/use-outside-click";
import Tooltip from "@/shared/ui/Tooltip";
import type { LLMOption } from "@/lib/llm-options";
import {
  effectiveReasoningEffort,
  reasoningEffortOptionsFromSupportedLevels,
  supportedReasoningEffortValues,
  type ReasoningEffortOption,
} from "@/lib/reasoning-effort";

/**
 * Per-conversation reasoning-effort override (#641), rendered beside the
 * model selector in the composer.
 *
 * The offered levels come from `supportedReasoningEffortValues`: the model's
 * live `supported_reasoning_efforts` list when the catalog publishes one,
 * otherwise the provider/model tables in `lib/reasoning-effort.ts`. Both
 * are narrowed to `VALID_REASONING_EFFORTS` — the wire vocabulary the turn
 * contract accepts — and a stored value the model does not support is never
 * re-listed; the selector shows Auto instead and the composer resets the
 * persisted override. A model with no selectable level hides the control.
 */
export default function ReasoningEffortSelector({
  option,
  value,
  onChange,
  disabled = false,
}: {
  /** The option backing the conversation's current model selection. */
  option: LLMOption | null;
  /** The conversation's override, or null for the provider default. */
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const options = useMemo<ReasoningEffortOption[]>(
    () => computeReasoningOptions(option),
    [option],
  );

  useOutsideClick(rootRef, open, () => setOpen(false));

  // Nothing to choose (only the implicit provider default): hide, per #641.
  if (!option || !options.some((item) => item.value)) return null;

  // A stored override the selected model does not support is not a
  // selectable level: render Auto as selected instead (#641). The composer
  // resets the persisted override once the model options are loaded.
  const selected = effectiveReasoningEffort(option, value) ?? "";
  const selectedLabel =
    options.find((item) => item.value === selected)?.label ?? selected;

  return (
    <div ref={rootRef} className="relative">
      <Tooltip label={t("Reasoning effort")} suppressed={open} side="top">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((current) => !current)}
          aria-label={t("Reasoning effort")}
          aria-expanded={open}
          className={`inline-flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
            disabled
              ? "cursor-not-allowed text-[var(--border)]"
              : open
                ? "bg-[var(--muted)] text-[var(--foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          }`}
        >
          <Brain size={16} strokeWidth={1.7} className="shrink-0" />
          <span className="min-w-0 whitespace-nowrap">
            {selected ? t(selectedLabel) : t("Auto")}
          </span>
        </button>
      </Tooltip>

      {open && !disabled && (
        <div className="absolute right-0 bottom-full z-50 mb-1.5 w-[min(220px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md">
          {options.map((item) => {
            const isSelected = item.value === selected;
            return (
              <button
                key={item.value || "default"}
                type="button"
                onClick={() => {
                  onChange(item.value || null);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                  isSelected
                    ? "bg-[var(--primary)]/[0.06]"
                    : "hover:bg-[var(--muted)]/45"
                }`}
              >
                <span
                  className={`min-w-0 flex-1 truncate text-[12.5px] font-medium ${
                    isSelected
                      ? "text-[var(--primary)]"
                      : "text-[var(--foreground)]"
                  }`}
                >
                  {t(item.label)}
                </span>
                {isSelected && (
                  <Check
                    size={14}
                    strokeWidth={2}
                    className="shrink-0 text-[var(--primary)]"
                  />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function computeReasoningOptions(
  option: LLMOption | null,
): ReasoningEffortOption[] {
  // Only levels the selected model supports, narrowed to the wire
  // vocabulary — the stored override is never re-added (#641).
  return reasoningEffortOptionsFromSupportedLevels(
    supportedReasoningEffortValues(option),
  );
}
