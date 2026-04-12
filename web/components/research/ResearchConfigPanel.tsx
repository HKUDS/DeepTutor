"use client";

import { ChevronDown } from "lucide-react";
import type {
  DeepResearchFormConfig,
  ResearchDepth,
  ResearchMode,
} from "@/lib/research-types";
import { summarizeResearchConfig } from "@/lib/research-types";
import { Field, INPUT_CLS } from "@/components/chat/home/composer-field";

interface ResearchConfigPanelProps {
  value: DeepResearchFormConfig;
  errors: Record<string, string>;
  collapsed: boolean;
  onChange: (next: DeepResearchFormConfig) => void;
  onToggleCollapsed: () => void;
}

const MODE_OPTIONS: Array<{ value: Exclude<ResearchMode, "">; label: string }> = [
  { value: "notes", label: "Study Notes" },
  { value: "report", label: "Report" },
  { value: "comparison", label: "Comparison" },
  { value: "learning_path", label: "Learning Path" },
];

const DEPTH_OPTIONS: Array<{ value: Exclude<ResearchDepth, "">; label: string }> = [
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
      <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]/60">{label}</span>
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

export default function ResearchConfigPanel({
  value,
  errors: _errors,
  collapsed,
  onChange,
  onToggleCollapsed,
}: ResearchConfigPanelProps) {
  const update = <K extends keyof DeepResearchFormConfig>(
    key: K,
    next: DeepResearchFormConfig[K],
  ) => onChange({ ...value, [key]: next });

  const summary = summarizeResearchConfig(value);

  return (
    <div>
      <button
        type="button"
        onClick={onToggleCollapsed}
        className="flex w-full items-center gap-1.5 px-3.5 py-1.5 text-left transition-colors hover:opacity-80"
      >
        <ChevronDown
          size={10}
          className={`shrink-0 text-[var(--muted-foreground)]/40 transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        <span className="text-[10px] font-medium text-[var(--muted-foreground)]/55">Settings</span>
        {collapsed && summary !== "Incomplete settings" && (
          <span className="min-w-0 truncate text-[10px] text-[var(--muted-foreground)]/30">— {summary}</span>
        )}
      </button>

      {!collapsed && (
        <div className="space-y-2 px-3.5 pb-2.5">
          <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
            <Field label="Mode" width="min-w-[130px] flex-1">
              <select
                value={value.mode}
                onChange={(e) => update("mode", e.target.value as ResearchMode)}
                className={`${INPUT_CLS} w-full`}
              >
                <option value="">Select...</option>
                {MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Depth" width="min-w-[130px] flex-1">
              <select
                value={value.depth}
                onChange={(e) => update("depth", e.target.value as ResearchDepth)}
                className={`${INPUT_CLS} w-full`}
              >
                <option value="">Select...</option>
                {DEPTH_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {value.depth === "manual" && (
            <div className="space-y-1.5 rounded-md bg-[var(--muted-foreground)]/5 px-3 py-2">
              <NumberSlider
                label="Sub-topics"
                value={value.manual_subtopics ?? 3}
                min={1}
                max={10}
                onChange={(n) => update("manual_subtopics", n)}
              />
              <NumberSlider
                label="Iterations"
                value={value.manual_max_iterations ?? 3}
                min={1}
                max={8}
                onChange={(n) => update("manual_max_iterations", n)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
