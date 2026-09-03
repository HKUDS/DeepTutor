"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";
import type {
  CatalogModel,
  ModelCapabilityKey,
} from "@/features/settings/store/SettingsStore";
import { selectClass, selectOptionClass } from "./shared";

type Defaults = { tools: boolean; vision: boolean; json_output: boolean };

const ROWS: { key: ModelCapabilityKey; label: string }[] = [
  { key: "tools", label: "Tool calling" },
  { key: "vision", label: "Image input" },
  { key: "json_output", label: "JSON output" },
  { key: "reasoning", label: "Reasoning controls" },
];

/**
 * Per-model capability overrides.
 *
 * Each row is a three-way choice: follow DeepTutor's built-in tables ("Auto",
 * shown together with what they currently say), or declare the answer. The
 * Auto values come from the backend so the UI never keeps a second copy of
 * the tables; the reasoning row's Auto is what the effort selector already
 * decided for this model.
 */
export function ModelCapabilityFields({
  binding,
  model,
  reasoningKnown,
  onChange,
}: {
  binding: string | undefined;
  model: CatalogModel;
  reasoningKnown: boolean;
  onChange: (key: ModelCapabilityKey, value: boolean | null) => void;
}) {
  const { t } = useTranslation();
  // Keyed by the model id it was fetched for, so a stale answer is never shown
  // against a different model while the next fetch is in flight.
  const [fetched, setFetched] = useState<{
    modelId: string;
    defaults: Defaults;
  } | null>(null);
  const modelId = (model.model || "").trim();
  const defaults = fetched?.modelId === modelId ? fetched.defaults : null;

  useEffect(() => {
    if (!modelId) return;
    let cancelled = false;
    const handle = window.setTimeout(async () => {
      try {
        const response = await apiFetch(
          apiUrl("/api/settings/model-capabilities"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ binding: binding ?? "", model: modelId }),
          },
        );
        if (!response.ok) return;
        const payload = (await response.json()) as { defaults?: Defaults };
        if (!cancelled && payload.defaults) {
          setFetched({ modelId, defaults: payload.defaults });
        }
      } catch {
        // Leave the Auto label without a value; the override still works.
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [binding, modelId]);

  const autoValue = (key: ModelCapabilityKey): boolean | null => {
    if (key === "reasoning") return reasoningKnown;
    return defaults ? defaults[key] : null;
  };

  return (
    <div className="sm:col-span-2">
      <div className="mb-1.5 text-[12px] text-[var(--muted-foreground)]">
        {t("Capabilities")}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {ROWS.map(({ key, label }) => {
          const declared = model.capabilities?.[key];
          const auto = autoValue(key);
          const autoLabel =
            auto === null
              ? t("Auto")
              : t("Auto ({{value}})", {
                  value: auto ? t("Supported") : t("Not supported"),
                });
          return (
            <label key={key} className="block">
              <span className="mb-1 block text-[11.5px] text-[var(--muted-foreground)]">
                {t(label)}
              </span>
              <span className="relative block">
                <select
                  className={selectClass}
                  value={declared === undefined ? "" : declared ? "yes" : "no"}
                  onChange={(event) => {
                    const next = event.target.value;
                    onChange(key, next === "" ? null : next === "yes");
                  }}
                >
                  <option className={selectOptionClass} value="">
                    {autoLabel}
                  </option>
                  <option className={selectOptionClass} value="yes">
                    {t("Supported")}
                  </option>
                  <option className={selectOptionClass} value="no">
                    {t("Not supported")}
                  </option>
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
              </span>
            </label>
          );
        })}
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Override what DeepTutor assumes about this model. Auto follows the built-in tables.",
        )}
      </p>
    </div>
  );
}
