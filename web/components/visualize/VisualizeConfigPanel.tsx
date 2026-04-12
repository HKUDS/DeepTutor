"use client";

import { useTranslation } from "react-i18next";
import type { VisualizeFormConfig } from "@/lib/visualize-types";
import { Field, INPUT_CLS } from "@/components/chat/home/composer-field";

interface VisualizeConfigPanelProps {
  value: VisualizeFormConfig;
  onChange: (next: VisualizeFormConfig) => void;
}

export default function VisualizeConfigPanel({
  value,
  onChange,
}: VisualizeConfigPanelProps) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap items-end gap-x-3 gap-y-2 px-3.5 py-2.5">
      <Field label="Render Mode" width="w-[120px]">
        <select
          value={value.render_mode}
          onChange={(e) =>
            onChange({ ...value, render_mode: e.target.value as VisualizeFormConfig["render_mode"] })
          }
          className={`${INPUT_CLS} w-full`}
        >
          <option value="auto">{t("Auto")}</option>
          <option value="chartjs">{t("Chart.js")}</option>
          <option value="svg">{t("SVG")}</option>
          <option value="mermaid">{t("Mermaid")}</option>
        </select>
      </Field>
    </div>
  );
}
