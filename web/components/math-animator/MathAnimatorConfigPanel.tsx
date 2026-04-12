"use client";

import type { MathAnimatorFormConfig } from "@/lib/math-animator-types";
import { Field, INPUT_CLS } from "@/components/chat/home/composer-field";

interface MathAnimatorConfigPanelProps {
  value: MathAnimatorFormConfig;
  onChange: (next: MathAnimatorFormConfig) => void;
}

export default function MathAnimatorConfigPanel({
  value,
  onChange,
}: MathAnimatorConfigPanelProps) {
  const update = <K extends keyof MathAnimatorFormConfig>(
    key: K,
    val: MathAnimatorFormConfig[K],
  ) => onChange({ ...value, [key]: val });

  return (
    <div className="flex flex-wrap items-end gap-x-3 gap-y-2 px-3.5 py-2.5">
      <Field label="Output" width="w-[100px]">
        <select
          value={value.output_mode}
          onChange={(e) => update("output_mode", e.target.value as MathAnimatorFormConfig["output_mode"])}
          className={`${INPUT_CLS} w-full`}
        >
          <option value="video">Video</option>
          <option value="image">Image</option>
        </select>
      </Field>

      <Field label="Quality" width="w-[100px]">
        <select
          value={value.quality}
          onChange={(e) => update("quality", e.target.value as MathAnimatorFormConfig["quality"])}
          className={`${INPUT_CLS} w-full`}
        >
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </Field>

      <Field label="Style Hint" width="min-w-[160px] flex-1">
        <input
          type="text"
          value={value.style_hint}
          onChange={(e) => update("style_hint", e.target.value)}
          placeholder="Style, pacing, color palette..."
          className={`${INPUT_CLS} w-full`}
        />
      </Field>
    </div>
  );
}
