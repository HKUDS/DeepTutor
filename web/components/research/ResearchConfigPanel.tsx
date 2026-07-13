"use client";

import { memo } from "react";
import { useTranslation } from "react-i18next";
import type {
  DeepResearchFormConfig,
  ResearchDepth,
  ResearchMode,
} from "@/lib/research-types";
import { summarizeResearchConfig } from "@/lib/research-types";
import {
  CollapsibleConfigSection,
  Field,
  INPUT_CLS,
} from "@/components/chat/home/composer-field";

interface ResearchConfigPanelProps {
  value: DeepResearchFormConfig;
  errors: Record<string, string>;
  /**
   * When provided, the panel is wrapped in a `CollapsibleConfigSection`.
   * Omit both to render bare for the chat Activity panel.
   */
  collapsed?: boolean;
  onChange: (next: DeepResearchFormConfig) => void;
  onToggleCollapsed?: () => void;
}

// Note: `label` values are i18n keys resolved via `t(...)` at render time so
// the dropdown options match the active UI language.
const MODE_OPTIONS: Array<{ value: Exclude<ResearchMode, "">; label: string }> =
  [
    { value: "notes", label: "Study Notes" },
    { value: "report", label: "Report" },
    { value: "comparison", label: "Comparison" },
    { value: "learning_path", label: "Learning Path" },
  ];

const DEPTH_OPTIONS: Array<{
  value: Exclude<ResearchDepth, "">;
  label: string;
}> = [
  { value: "quick", label: "Quick" },
  { value: "standard", label: "Standard" },
  { value: "deep", label: "Deep" },
  { value: "manual", label: "Manual" },
];

function NumberSlider({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]/60">
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-[var(--muted-foreground)]/15 accent-[var(--primary)] [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--primary)]"
      />
      <span className="w-5 text-center text-[11px] font-semibold tabular-nums text-[var(--foreground)]">
        {value}
      </span>
    </div>
  );
}

export default memo(function ResearchConfigPanel({
  value,
  errors: _errors,
  collapsed,
  onChange,
  onToggleCollapsed,
}: ResearchConfigPanelProps) {
  const { t } = useTranslation();
  const update = <K extends keyof DeepResearchFormConfig>(
    key: K,
    next: DeepResearchFormConfig[K],
  ) => onChange({ ...value, [key]: next });

  const rawSummary = summarizeResearchConfig(value, t);
  const summary =
    rawSummary === t("Incomplete settings") ? undefined : rawSummary;

  const body = (
    <>
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <Field label={t("Mode")} width="min-w-[130px] flex-1">
          <select
            value={value.mode}
            onChange={(e) => update("mode", e.target.value as ResearchMode)}
            className={`${INPUT_CLS} w-full`}
          >
            <option value="">{t("Select...")}</option>
            {MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("Depth")} width="min-w-[130px] flex-1">
          <select
            value={value.depth}
            onChange={(e) => update("depth", e.target.value as ResearchDepth)}
            className={`${INPUT_CLS} w-full`}
          >
            <option value="">{t("Select...")}</option>
            {DEPTH_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {value.depth === "manual" && (
        <div className="space-y-1.5 rounded-md bg-[var(--muted-foreground)]/5 px-3 py-2">
          <NumberSlider
            label={t("Sub-topics")}
            value={value.manual_subtopics ?? 3}
            min={1}
            max={10}
            onChange={(n) => update("manual_subtopics", n)}
          />
          <NumberSlider
            label={t("Iterations")}
            value={value.manual_max_iterations ?? 3}
            min={1}
            max={8}
            onChange={(n) => update("manual_max_iterations", n)}
          />
        </div>
      )}
    </>
  );

  if (collapsed === undefined) {
    return <div className="space-y-2 px-3.5 py-2.5">{body}</div>;
  }

  return (
    <CollapsibleConfigSection
      collapsed={collapsed}
      summary={summary}
      onToggleCollapsed={onToggleCollapsed ?? (() => undefined)}
      bodyClassName="space-y-2 px-3.5 pb-2.5"
    >
      {body}
    </CollapsibleConfigSection>
  );
});
